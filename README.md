Implementing a Query‑Conditioned Radiative–Perceptual Utility Field

A query‑conditioned radiative–perceptual utility field aims to represent every street segment by a vector of physical and perceptual features and lets users specify their preferences (e.g., coolness vs. scenicness). A routing engine then finds paths that maximize the user’s utility subject to distance or time constraints. The idea requires merging high‑resolution micro‑climate modelling with perceptual metrics such as visible greenery, scenic quality and noise. Below is a detailed plan for building such a system.

1. Data acquisition and preprocessing
Pedestrian street network. Use OpenStreetMap via OSMnx to download the pedestrian network for the city. This gives nodes, edges, geometry and road attributes. OSMnx has built‑in functions for cleaning networks and converting them into graph structures.
3‑D urban geometry. Obtain high‑resolution digital surface models (DSM) and digital elevation models (DEM). In the U.S., the USGS 3DEP LiDAR program offers open DSM/DEM data. Use local building footprint data (city or county open GIS) for building heights when available. Assemble a tree canopy model by combining LiDAR with overhead imagery (e.g. NAIP, Sentinel‑2) to delineate vegetation height and density.
Meteorological forcing. Collect hourly weather data for air temperature, relative humidity, wind speed, solar irradiance and atmospheric pressure. The National Solar Radiation Database (NSRDB) provides solar radiation, while local weather stations supply temperature and humidity.
Land‑cover and albedo data. Acquire land‑cover maps to assign surface type (asphalt, grass, water, etc.) and reflectivity values. Sentinel‑2 or national land‑cover databases (e.g., NLCD) can provide this information.
Street‑level imagery and scenic data. Download street‑view images (Google Street View, Mapillary) for each road segment. For subjective scenicness or greenery, compute metrics such as Green View Index using deep‑learning models. Where available, use datasets like ScenicOrNot or Place Pulse to calibrate scenic perception. The pleasant pedestrian routing system used OSM features (parks, squares, trees, shops) to let users decide how much green or social activity they want along a route
.
Noise exposure and traffic volume. Combine OpenStreetMap, socio‑economic data and open GPS trajectory data to estimate traffic volumes and noise levels. The HeiGIT quiet‑route project derives traffic‑related variables and uses a noise model to estimate noise exposure; it then proposes a routing algorithm that minimizes noise while respecting a distance constraint. Adopt similar methods to attach a noise metric to each edge.
Ancillary context layers. Include layers for slope (derived from DEM), proximity to water bodies (cooling effect), and points of interest (parks, cafés, benches). Integrate free datasets such as municipal tree inventories where available.
2. Radiative micro‑climate modelling
High‑resolution UTCI mapping. Use the SOLWEIG‑GPU model (Solar and LongWave Environmental Irradiance Geometry) to compute Universal Thermal Climate Index (UTCI) across the study area. SOLWEIG‑GPU calculates sky view factor, mean radiant temperature and UTCI at pedestrian height using DSM, DEM, tree canopy and meteorological inputs. The GPU‑accelerated version can create 2‑m resolution UTCI rasters for city‑scale domains.
Workflow. Divide the city into tiles and prepare input layers: (i) building DSM, (ii) DEM, (iii) tree‑height DSM, and (iv) land‑cover/albedo. Provide hourly meteorological data. SOLWEIG‑GPU computes radiative fluxes (direct and diffuse short‑wave, long‑wave radiation) and generates a UTCI value for each grid cell. Running this for different hours produces time‑dependent heat maps.
Radiative features for edges. Overlay the street network onto the UTCI raster. Densify each road polyline (e.g. sample every 4 m) and extract the UTCI value at each point. For each edge, compute:
Mean, minimum and maximum UTCI.
Heat dose: integrate UTCI above a comfort threshold (e.g. UTCI > 26 °C) over the edge length to represent cumulative heat exposure.
Shade fraction: proportion of points where UTCI is below a coolness percentile (e.g. lower 10 %).
Residual correction with mobile sensing. Deploy low‑cost sensors (or use community sensors) to collect pedestrian‑level air temperature, humidity and globe temperature along routes. Use these measurements to compute UTCI via tools like RayMan and calibrate the SOLWEIG‑derived heat field. The Dresden micro‑climate mapping project showed how mobile devices can map UTCI and identify hotspots. Fit a residual model (e.g. Gaussian process regression) to correct systematic bias in the model.
3. Perceptual metrics
Scenicness / greenery. Use deep‑learning models on street‑view images to predict visible greenery and scenicness ratings. The pleasant pedestrian routing system allows users to set how much green space and social activity they desire along a route
. Adopt a similar feature set: number of parks, tree‑lined streets, café density, water views. Normalize each feature to [0, 1].
Noise exposure. Following HeiGIT’s quiet‑route approach, estimate traffic volumes from OSM, socio‑economic and GPS data and apply a noise model to derive noise levels. Assign each street segment a noise score.
Other perceptual factors. Compute additional scores such as: slope steepness (from DEM), safety (crime statistics or lighting), accessibility (sidewalk width, curb ramps), and visibility (open vs. closed spaces). These become additional dimensions in the perceptual field.
4. Feature vector construction

For each street edge e, build a feature vector z_e(t) that depends on time t (hour of day) and includes:

Distance and travel time.
Radiative metrics: mean UTCI, heat dose, shade fraction at time t (radiative features).
Perceptual metrics: scenicness/greenery score, noise level, slope, POI density, safety index.
Uncertainty estimates: variance from residual model or data sparsity.

Normalize or rescale features to comparable ranges. This vector forms the basis of the utility field.

5. Query‑conditioned utility function
User preference vector. Represent a user’s priorities (e.g., coolness vs. scenicness vs. quietness) by a weight vector w with elements corresponding to each feature in z_e. For example, w_cool emphasises low heat dose, w_scenic emphasises high scenicness, and w_noise emphasises low noise.
Hyper‑network or meta‑model. Instead of manually assigning weights, train a hyper‑network that maps a compact user descriptor (heat sensitivity, desire for greenery, noise aversion, mobility mode) to the weight vector. Hyper‑network approaches for personalised route optimisation have achieved high accuracy and mAP in recommending scenic travel itineraries. Use crowd‑sourced route preferences or agent‑based simulations to train this model.

Utility calculation. For a query (origin, destination, context, preference), compute the cost of traversing edge e at time t as:

cost(e)=w⋅z
e
	​

(t)+β⋅uncertainty(e)

where β penalizes high uncertainty. For multi‑objective scenarios, you may adopt a resource‑constrained shortest‑path formulation: first compute the baseline shortest path length d*, then find the route that maximizes utility subject to distance ≤ (1 + δ)·d* (where δ is the allowed detour ratio).

6. Route optimisation
Graph preparation. Create a time‑expanded graph if necessary (e.g., separate nodes for each hour). For each edge, compute the time‑dependent feature vector z_e(t).
Search algorithm. Use a multi‑objective A* or bi‑objective Dijkstra algorithm that can incorporate utility and distance simultaneously. When using the resource‑constrained model, apply algorithms designed for resource‑constrained shortest paths to ensure the result stays within the distance budget.
Pareto frontier and user choice. Generate multiple candidate routes representing different trade‑offs (e.g., slightly longer but much cooler vs. shortest but less scenic). Present these on a map with colour coding and summary statistics. Provide the user with slider or natural language interface to refine their preference vector.
7. Natural‑language interface and user interaction
Implement a hierarchical large‑language‑model (LLM) interface similar to RouteLLM, where a manager agent parses natural‑language queries (e.g., “Find me a shaded route with few hills and nice views”) and sub‑agents resolve constraints, retrieve POIs and assign weight vectors.
Provide an interactive map (e.g., CesiumJS or Leaflet) that displays candidate routes with colour‑coded heat/stress levels. Show details such as mean UTCI, scenicness score, shade percentage and noise level.
8. Evaluation and calibration
Field validation. Use GPS‑linked micro‑climate measurements (temperature, humidity, globe temperature) to compare predicted UTCI and heat dose against observed values. Identify biases and iteratively refine the radiative model with residual corrections.
User studies. Conduct surveys or pairwise preference tests where participants choose between routes generated by your system and by baseline methods (shortest path or simple shade heuristic). Evaluate whether users perceive the “coolest” routes as more comfortable and whether scenic or quiet routes align with subjective perceptions.
Impact assessment. Analyse the reduction in heat dose or noise exposure for various user groups (e.g., elderly, cyclists) and evaluate how small infrastructure interventions (e.g., planting trees along 1.5 % of streets) can reduce network‑wide heat exposure, as shown in the New York cycling study.
9. Iterative improvements and deployment
Scalability: design the pipeline to work at city scale by leveraging GPU acceleration for SOLWEIG and vectorised operations for feature extraction. Use caching for pre‑computed fields and incremental updates as new data (weather, construction) arrives.
Adaptability: ensure that the hyper‑network can incorporate new objectives (air quality, safety, energy expenditure) without retraining the base model. Extend the feature vector accordingly.
Open source and reproducibility: follow open data standards and publish code and datasets when possible. Document the methodology to allow replication in other cities.
Summary

The query‑conditioned radiative–perceptual utility field merges physical micro‑climate modelling with human perception to enable personalised, time‑aware routing. High‑resolution UTCI maps generated by SOLWEIG‑GPU provide radiative features, while perceptual features like scenicness, greenery, noise and slope are computed from street‑view imagery and socio‑economic data
. Each street edge receives a feature vector capturing these attributes. A hyper‑network translates user preferences into a weight vector that scores edges, and a resource‑constrained path‑finding algorithm finds routes that maximise user utility without large detours. Crowdsourced sensor data and user feedback calibrate and validate the model. By unifying radiative and perceptual information in a single framework, the system can answer queries like “cool and quiet” or “shady and scenic” without needing separate algorithms for each scenario.
