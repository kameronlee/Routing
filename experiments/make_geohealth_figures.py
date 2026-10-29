"""Build the paper's vector figures from archived routes and frozen GIS context.

The optional --fetch-context flag downloads public DDOT/OCTO background layers.
Background geometry never enters the routing calculation or exposure metrics.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon as MplPolygon, Rectangle
from matplotlib import patheffects
from rasterio.warp import transform, transform_geom
from shapely.geometry import shape, box

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "paper_assets/review3466"
CONTEXT = ASSETS / "figure_inputs"
METHODS = ["shortest_distance", "azimuth_heuristic", "shadow_only", "heat_dose", "proposed_full"]
NAMES = ["Shortest distance", "Hybrid azimuth", "Direct shadow", "UTCI exceedance", "Composite"]
COLORS = ["#242424", "#A6761D", "#7570B3", "#007A6E", "#2166AC"]
LINESTYLES = ["-", (0, (5, 2)), (0, (1, 1.5)), (0, (4, 1.5, 1, 1.5)), "-"]
SOURCE_BASE = "https://maps2.dcgis.dc.gov/dcgis/rest/services/"
ROAD_URL = SOURCE_BASE + "DCGIS_DATA/Transportation_WebMercator/MapServer/163"
WATER_URL = SOURCE_BASE + "DCGIS_DATA/Planimetrics_2023/MapServer/14"


def load_json(path):
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return json.loads(data)


def write_gzip_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    path.write_bytes(gzip.compress(payload, mtime=0))


def read_csv(name):
    path = ASSETS / "raw" / name
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    with gzip.open(path.with_suffix(path.suffix + ".gz"), "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def source_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_cases(routes):
    index = {(r["pair_id"], float(r["detour_ratio"]), r["method"]): r for r in routes}
    candidates = []
    for row in routes:
        if row["method"] != "heat_dose" or float(row["detour_ratio"]) != .2:
            continue
        key = row["pair_id"]
        if all(index[(key, .2, m)]["success"] == "true" for m in METHODS):
            base = index[(key, .2, "shortest_distance")]
            candidates.append((float(base["heat_dose"]) - float(row["heat_dose"]), key))
    cases = []
    for quantile, panel in [(.5, "a"), (.1, "b")]:
        target = float(np.quantile([x[0] for x in candidates], quantile))
        delta, pair_id = min(candidates, key=lambda x: (abs(x[0] - target), x[1]))
        cases.append({"panel": panel, "quantile": quantile, "target_delta_H_K": target,
                      "delta_H_K": delta, "pair_id": pair_id, "budget": .2,
                      "common_records_at_budget": len(candidates)})
    return cases


def fetch_context():
    import requests
    CONTEXT.mkdir(parents=True, exist_ok=True)
    records = {}
    for name, url, fields in [
        ("roads", ROAD_URL, "OBJECTID,ROUTENAME,ROADTYPE"),
        ("water", WATER_URL, "OBJECTID,DESCRIPTION,CAPTUREYEAR"),
    ]:
        features, offset = [], 0
        while True:
            params = {"f": "geojson", "where": "1=1", "outFields": fields,
                      "outSR": 32618, "returnZ": "false", "returnM": "false",
                      "orderByFields": "OBJECTID", "resultOffset": offset,
                      "resultRecordCount": 2000, "geometryPrecision": 3}
            response = requests.get(url + "/query", params=params, timeout=45)
            response.raise_for_status()
            page = response.json()
            if "error" in page:
                raise RuntimeError(page["error"])
            batch = page.get("features", [])
            features.extend(batch)
            if len(batch) < 2000 and not page.get("exceededTransferLimit", False):
                break
            if not batch:
                raise RuntimeError("Empty truncated GIS response")
            offset += len(batch)
        ids = [f["properties"]["OBJECTID"] for f in features]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate GIS object IDs during pagination")
        payload = {"type": "FeatureCollection", "features": features,
                   "crs": {"type": "name", "properties": {"name": "EPSG:32618"}}}
        path = CONTEXT / (name + ".geojson.gz")
        write_gzip_json(path, payload)
        records[name] = {"url": url, "feature_count": len(features), "retrieved": date.today().isoformat(),
                         "sha256": source_digest(path)}
        print(name, len(features), "features")
    boundary = load_json(ROOT / "data/raw/boundary/dc_boundary.geojson")
    for f in boundary["features"]:
        f["geometry"] = transform_geom("EPSG:4326", "EPSG:32618", f["geometry"])
    write_gzip_json(CONTEXT / "district.geojson.gz", boundary)
    records["district"] = {"source": "Existing DC GIS boundary in data/raw/boundary/dc_boundary.geojson",
                            "sha256": source_digest(CONTEXT / "district.geojson.gz")}
    records["scope"] = "Context only; not the historical routing graph, shade map, or UTCI field."
    records["attribution"] = "Roadway Block: DDOT, CC BY 4.0. Waterbodies 2023 and district boundary: DC OCTO/DC GIS."
    (CONTEXT / "sources.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def freeze_cases(geojson_path, cases):
    source_bytes = geojson_path.read_bytes()
    data = json.loads(source_bytes)
    required = {(c["pair_id"], .2, m) for c in cases for m in ["shortest_distance", "heat_dose"]}
    features = []
    for feature in data["features"]:
        r = feature["properties"]
        key = (r["pair_id"], float(r["detour_ratio"]), r["method"])
        if key in required:
            feature["geometry"] = transform_geom("EPSG:4326", "EPSG:32618", feature["geometry"])
            features.append(feature)
    if len(features) != 4:
        raise ValueError("Expected four uniquely identified archived route geometries")
    write_gzip_json(CONTEXT / "route_cases.geojson.gz", {"type": "FeatureCollection", "features": features})
    (CONTEXT / "route_cases_source.json").write_text(json.dumps({
        "source_file": "dc_snapshot_500pair_main_methods/routes.geojson",
        "sha256_full_source": hashlib.sha256(source_bytes).hexdigest(),
        "selection": "Nearest observed paired H reduction to the median and tenth percentile at 20% allowance, among all-method common successful records; ties by OD ID.",
        "cases": cases, "output_crs": "EPSG:32618", "geometry_changed": "Coordinate projection only."
    }, indent=2) + "\n", encoding="utf-8")


def geometry_parts(geom, kind):
    if geom.is_empty:
        return
    if geom.geom_type == kind:
        yield geom
    elif hasattr(geom, "geoms"):
        for item in geom.geoms:
            yield from geometry_parts(item, kind)


def geographic_context():
    roads = [(shape(f["geometry"]), f["properties"].get("ROUTENAME", ""))
             for f in load_json(CONTEXT / "roads.geojson.gz")["features"] if f.get("geometry")]
    water = [shape(f["geometry"]) for f in load_json(CONTEXT / "water.geojson.gz")["features"] if f.get("geometry")]
    district = shape(load_json(CONTEXT / "district.geojson.gz")["features"][0]["geometry"])
    return roads, water, district


def draw_context(ax, roads, water, district, bounds, *, overview=False):
    clip = box(*bounds)
    ax.set_facecolor("#FFFFFF")
    land = district.intersection(clip)
    for poly in geometry_parts(land, "Polygon"):
        ax.add_patch(MplPolygon(np.asarray(poly.exterior.coords) / 1000, facecolor="#F8F8F5", edgecolor="none", zorder=0))
    for geom in water:
        if geom.intersects(clip):
            for poly in geometry_parts(geom.intersection(clip), "Polygon"):
                ax.add_patch(MplPolygon(np.asarray(poly.exterior.coords) / 1000, facecolor="#DDE8EC", edgecolor="none", zorder=1))
                for hole in poly.interiors:
                    ax.add_patch(MplPolygon(np.asarray(hole.coords) / 1000, facecolor="#F8F8F5", edgecolor="none", zorder=1))
    lines, labelled = [], []
    for geom, name in roads:
        if geom.intersects(clip):
            for line in geometry_parts(geom.intersection(clip), "LineString"):
                lines.append(np.asarray(line.coords)[:, :2] / 1000)
                if name:
                    labelled.append((line.length, line, name))
    ax.add_collection(LineCollection(lines, colors="#C4C4C0" if not overview else "#D4D4D0",
                                     linewidths=.36 if not overview else .20, zorder=2))
    boundary = district.boundary.intersection(clip)
    ax.add_collection(LineCollection([np.asarray(x.coords) / 1000 for x in geometry_parts(boundary, "LineString")],
                                     colors="#777773", linewidths=.6, zorder=3))
    ax.set(xlim=(bounds[0]/1000,bounds[2]/1000), ylim=(bounds[1]/1000,bounds[3]/1000), aspect="equal")
    for spine in ax.spines.values():
        spine.set_linewidth(.55)
        spine.set_color("#777777")
    ax.tick_params(length=2.5, width=.5, pad=3, labelsize=8)
    return sorted(labelled, key=lambda x: x[0], reverse=True)


def scale_bar(ax, length_km, *, xpos=.07, ypos=.075):
    xmin,xmax=ax.get_xlim();ymin,ymax=ax.get_ylim()
    x=xmin+xpos*(xmax-xmin);y=ymin+ypos*(ymax-ymin)
    ax.plot([x,x+length_km],[y,y],color="white",lw=5,zorder=8,solid_capstyle="butt")
    ax.plot([x,x+length_km],[y,y],color="#222222",lw=1.5,zorder=9,solid_capstyle="butt")
    ax.text(x+length_km/2,y+.018*(ymax-ymin),f"{length_km:g} km",ha="center",va="bottom",fontsize=8,zorder=10,
            path_effects=[patheffects.withStroke(linewidth=2.5,foreground="white")])


def save_figure(fig, path):
    # Labels retain their stated point size when included at the native 7 in width.
    assert all(t.get_fontsize() >= 8 for t in fig.findobj(matplotlib.text.Text))
    fig.savefig(path, metadata={"Creator": "Matplotlib; archived routes and DC GIS context", "CreationDate": None})
    fig.savefig(path.with_suffix(".png"), dpi=300)
    plt.close(fig)


def route_comparison(cases, routes, context, out):
    records={(r["pair_id"],float(r["detour_ratio"]),r["method"]):r for r in routes}
    features=load_json(CONTEXT / "route_cases.geojson.gz")["features"]
    shapes={(f["properties"]["pair_id"],f["properties"]["method"]):shape(f["geometry"]) for f in features}
    roads,water,district=context
    fig=plt.figure(figsize=(7.0,3.7))
    extents=[]
    for i,c in enumerate(cases):
        a=shapes[(c['pair_id'],'shortest_distance')];b=shapes[(c['pair_id'],'heat_dose')]
        base=records[(c['pair_id'],.2,'shortest_distance')];alt=records[(c['pair_id'],.2,'heat_dose')]
        # Verify that every map corresponds to the exact archived comparison.
        assert abs(float(base['heat_dose'])-float(alt['heat_dose'])-c['delta_H_K'])<1e-12
        for method,row in [('shortest_distance',base),('heat_dose',alt)]:
            feature=next(f for f in features if f['properties']['pair_id']==c['pair_id'] and f['properties']['method']==method)
            for key in ['route_distance_m','heat_dose','edge_ids']:
                assert str(feature['properties'][key])==str(row[key]),f'Geometry/summary mismatch: {key}'
        bb=a.union(b).bounds;cx=(bb[0]+bb[2])/2;cy=(bb[1]+bb[3])/2
        bounds=(cx-950,cy-650,cx+950,cy+650);extents.append(bounds)
        ax=fig.add_axes([.03+i*.50,.345,.44,.55])
        draw_context(ax,roads,water,district,bounds)
        shared=a.intersection(b)
        assert a.difference(b).union(b.difference(a)).union(shared).symmetric_difference(a.union(b)).length < 1e-6
        # Exact geometric intersections are drawn once; no buffering or map offset.
        for geom,color,lw,ls in [(shared,'#858585',2.1,'-'),
                                  (a.difference(b),'#252525',2.0,'-'),
                                  (b.difference(a),'#007A6E',2.15,(0,(4,1.8)))]:
            parts=[np.asarray(line.coords)/1000 for line in geometry_parts(geom,'LineString')]
            ax.add_collection(LineCollection(parts,colors='white',linewidths=lw+1.7,capstyle='round',joinstyle='round',zorder=5))
            ax.add_collection(LineCollection(parts,colors=color,linewidths=lw,linestyles=ls,capstyle='round',joinstyle='round',zorder=6))
        xy=np.asarray(a.coords)/1000
        for pt,label,marker in [(xy[0],'O','o'),(xy[-1],'D','s')]:
            ax.plot(*pt,marker=marker,ms=5,mec='#222222',mew=.9,mfc='white',zorder=8)
            ax.annotate(label,pt,xytext=(6,6),textcoords='offset points',fontsize=9,weight='bold',zorder=9,
                        path_effects=[patheffects.withStroke(linewidth=3,foreground='white')])
        ax.set_xticks([]);ax.set_yticks([])
        scale_bar(ax,.5)
        title='Median case' if i==0 else 'Lower-tail case'
        fig.text(.03+i*.50,.97,f"({c['panel']}) {title}",fontsize=10,fontweight='bold')
        fig.text(.03+i*.50,.925,f"{c['pair_id']}; 20% distance allowance",fontsize=8.5)
        x=.03+i*.50
        for ypos,method,length,heat in [(.295,'Route','Length (km)','H (K)'),
                (.245,'Shortest',f"{float(base['route_distance_m'])/1000:.2f}",f"{float(base['heat_dose']):.2f}"),
                (.195,'UTCI exceedance',f"{float(alt['route_distance_m'])/1000:.2f}",f"{float(alt['heat_dose']):.2f}")]:
            fig.text(x,ypos,method,fontsize=9)
            fig.text(x+.29,ypos,length,ha='right',fontsize=9)
            fig.text(x+.44,ypos,heat,ha='right',fontsize=9)
        fig.text(x,.135,f"ΔH = {c['delta_H_K']:+.2f} K; extra distance = {float(alt['excess_distance_ratio'])*100:.1f}%",fontsize=9)
    fig.legend(handles=[Line2D([0],[0],color='#252525',lw=2,label='Shortest only'),
                        Line2D([0],[0],color='#007A6E',lw=2.1,ls=(0,(4,1.8)),label='UTCI exceedance only'),
                        Line2D([0],[0],color='#858585',lw=2.1,label='Shared geometry')],
               loc='lower center',bbox_to_anchor=(.5,-.005),ncol=3,frameon=False,fontsize=9,handlelength=2.5,columnspacing=1.5)
    fig.text(.5,.075,'H: mean positive UTCI exceedance; ΔH = shortest − UTCI exceedance',ha='center',fontsize=8.5)
    save_figure(fig,out/'route_comparison.pdf')
    return extents


def study_area(od,context,extents,out):
    roads,water,district=context
    fig=plt.figure(figsize=(7,3.55))
    ax=fig.add_axes([.025,.13,.43,.76])
    bb=district.bounds;cx=(bb[0]+bb[2])/2;cy=(bb[1]+bb[3])/2
    bounds=(cx-11100,cy-11800,cx+11100,cy+11800)
    draw_context(ax,roads,water,district,bounds,overview=True)
    lon=[float(r[k]) for r in od for k in ['origin_lon','destination_lon']]
    lat=[float(r[k]) for r in od for k in ['origin_lat','destination_lat']]
    x,y=transform('EPSG:4326','EPSG:32618',lon,lat)
    # Locations are plotted without artificial links between endpoints.
    ax.scatter(np.asarray(x)/1000,np.asarray(y)/1000,s=4,color='#1F5C85',alpha=.62,linewidths=0,zorder=4)
    for i,(a,b,c,d) in enumerate(extents):
        ax.add_patch(Rectangle((a/1000,b/1000),(c-a)/1000,(d-b)/1000,fill=False,edgecolor='#111111',lw=.8,zorder=5))
        ax.text(c/1000+.12,d/1000,f"2{'ab'[i]}",fontsize=8.5,weight='bold',va='bottom',zorder=6,
                path_effects=[patheffects.withStroke(linewidth=2.5,foreground='white')])
    scale_bar(ax,5)
    ax.set_xticks([]);ax.set_yticks([])
    fig.text(.025,.95,'(a) Sampled endpoints',fontsize=10,weight='bold')
    ax.text(.03,.96,'Washington, DC',transform=ax.transAxes,va='top',fontsize=9,
            bbox={'facecolor':'white','edgecolor':'none','alpha':.85,'pad':2})
    ax.text(.97,.97,'N',transform=ax.transAxes,ha='center',va='top',fontsize=9)
    ax.annotate('',xy=(.97,.94),xytext=(.97,.83),xycoords='axes fraction',arrowprops={'arrowstyle':'-|>','lw':.7,'color':'#333333'})
    hist=fig.add_axes([.575,.24,.39,.59])
    lengths=np.asarray([float(r['baseline_shortest_distance_m'])/1000 for r in od])
    counts,_,_=hist.hist(lengths,bins=np.arange(.4,3.0001,.2),color='#6D8697',edgecolor='white',linewidth=.7)
    assert int(counts.sum())==len(od)==500
    hist.axvline(.4,color='#444444',lw=.8,ls=(0,(3,3)))
    hist.axvline(3.0,color='#444444',lw=.8,ls=(0,(3,3)))
    hist.set(xlabel='Original-network shortest distance (km)',ylabel='OD pairs',xlim=(.3,3.1))
    hist.set_xticks([.4,1,1.6,2.2,2.8]);hist.set_ylim(0,70)
    hist.spines[['top','right']].set_visible(False)
    hist.tick_params(length=3,width=.6)
    fig.text(.575,.95,'(b) Network-distance eligibility',fontsize=10,weight='bold')
    hist.text(.5,1.035,f'500 pairs; observed range {lengths.min():.3f}–{lengths.max():.3f} km',transform=hist.transAxes,ha='center',va='bottom',fontsize=8.5)
    hist.text(.43,67,'Lower limit',fontsize=8,va='top')
    hist.text(2.97,67,'Upper limit',fontsize=8,ha='right',va='top')
    fig.text(.025,.065,'Blue: sampled endpoints; boxes: Fig. 2 map extents',fontsize=8.5)
    save_figure(fig,out/'study_area.pdf')


def runtime_ecdf(routes,out):
    fig,axes=plt.subplots(1,2,figsize=(7,3.4),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.985,top=.84,bottom=.40,wspace=.17)
    summaries=[]
    for j,(accepted,title) in enumerate([(True,'Accepted attempts'),(False,'Rejected attempts')]):
        ax=axes[j]
        count=0
        for method,name,color,linestyle in zip(METHODS,NAMES,COLORS,LINESTYLES):
            values=np.sort([float(r['runtime_ms'])/1000 for r in routes if r['method']==method and (r['success']=='true')==accepted])
            if not len(values):continue
            if not np.all(np.isfinite(values)) or values[0] <= 0 or values[0] < .07 or values[-1] > 12:
                raise ValueError('Runtime data are non-finite, non-positive, or outside the displayed range')
            count+=len(values)
            ax.step(np.r_[.07,values,12],np.r_[0,np.arange(1,len(values)+1)/len(values),1],where='post',lw=1.2,color=color,ls=linestyle,label=name,zorder=7-METHODS.index(method))
            summaries.append({'method':method,'success':accepted,'n':len(values),'min_s':float(values[0]),'median_s':float(np.median(values)),
                              'p90_s':float(np.quantile(values,.9)),'max_s':float(values[-1])})
        ax.set_xscale('log');ax.set_xlim(.07,12);ax.set_ylim(0,1.02)
        ax.set_xticks([.1,.3,1,3,10]);ax.set_xticklabels(['0.1','0.3','1','3','10'])
        ax.set_yticks([0,.25,.5,.75,1]);ax.set_yticklabels(['0','0.25','0.50','0.75','1.00'])
        ax.grid(axis='y',color='#D9D9D9',lw=.45)
        ax.spines[['top','right']].set_visible(False)
        ax.tick_params(which='minor',bottom=False)
        ax.set_xlabel('End-to-end runtime (s; log scale)',fontsize=9)
        ax.set_title(f"({'ab'[j]}) {title}",loc='left',fontsize=10,weight='bold',pad=21)
        ax.text(0,1.035,f"n = {count:,} attempts",transform=ax.transAxes,fontsize=8.5,va='bottom')
    axes[0].set_ylabel('Empirical cumulative proportion',fontsize=9)
    handles=[]
    for method,color,name,ls in zip(METHODS,COLORS,NAMES,LINESTYLES):
        accepted=sum(r['method']==method and r['success']=='true' for r in routes)
        rejected=sum(r['method']==method and r['success']!='true' for r in routes)
        handles.append(Line2D([0],[0],color=color,lw=1.4,ls=ls,label=f'{name} ({accepted:,} / {rejected:,})'))
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.005),ncol=2,frameon=False,fontsize=8.5,columnspacing=2,handlelength=2.5,
               title='Method (accepted / rejected attempts)',title_fontsize=8.5)
    save_figure(fig,out/'runtime_ecdf.pdf')
    with (out/'runtime_ecdf_summary.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(summaries[0]));writer.writeheader();writer.writerows(summaries)


def build_figures(routes=None,od=None,out=None):
    routes=routes if routes is not None else read_csv('routes_summary.csv')
    od=od if od is not None else read_csv('od_pairs.csv')
    out=Path(out or ASSETS/'analysis');out.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'STIXGeneral','mathtext.fontset':'stix','font.size':9,
                         'axes.labelsize':9,'xtick.labelsize':8,'ytick.labelsize':8,
                         'pdf.fonttype':42,'ps.fonttype':42,'axes.linewidth':.6})
    cases=selected_cases(routes)
    stored=load_json(CONTEXT/'route_cases_source.json')
    assert stored['cases']==cases,'Route selection changed; regenerate and audit the case geometries.'
    context=geographic_context()
    extents=route_comparison(cases,routes,context,out)
    study_area(od,context,extents,out)
    runtime_ecdf(routes,out)
    audit={'cases':cases,'context_scope':'Geographic display only; not an input to routing or exposure evaluation.',
           'context_sha256':{p.name:source_digest(p) for p in sorted(CONTEXT.glob('*.gz'))},
           'map_crs':'EPSG:32618','map_case_extent_m':[1900,1300],'runtime_records':len(routes),
           'runtime_success_records':sum(r['success']=='true' for r in routes),
           'runtime_values_plotted':'All observed finite positive runtimes; one ECDF per method and status.',
           'software':{'matplotlib':matplotlib.__version__,'numpy':np.__version__}}
    (out/'figure_audit.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(audit,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch-context',action='store_true')
    parser.add_argument('--routes-geojson',type=Path,help='Original route geometries; needed only to create the frozen four-route subset.')
    args=parser.parse_args()
    if args.fetch_context:fetch_context()
    if args.routes_geojson:freeze_cases(args.routes_geojson,selected_cases(read_csv('routes_summary.csv')))
    build_figures()


if __name__=='__main__':main()
