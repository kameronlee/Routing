import { Platform } from 'react-native';

export type MapCoordinate = {
  latitude: number;
  longitude: number;
  snapToleranceM?: number;
};

type BackendCoordinate = {
  lat: number;
  lon: number;
};

type BackendRouteCandidate = {
  geometry: BackendCoordinate[];
  edge_ids: string[];
  distance_m: number;
  duration_s: number;
  mean_utci: number;
  max_utci: number;
  heat_dose: number;
  shade_fraction: number;
  scenic_score: number;
  noise_score: number;
  slope_penalty: number;
  cost: number;
};

type BackendRouteResponse = {
  graph_source: string;
  origin_node: string;
  destination_node: string;
  origin_snap_distance_m: number;
  destination_snap_distance_m: number;
  removed_no_utci_edges: number;
  utci_source: string | null;
  utci_time: string | null;
  requested_departure_time: string;
  uses_nearest_time: boolean;
  search_truncated: boolean;
  warnings: string[];
  candidates: BackendRouteCandidate[];
};

export type RouteComparison = {
  standard_total_meters: number;
  cool_total_meters: number;
  extra_distance_meters: number;
  standard_shade_score: number;
  cool_shade_score: number;
  shade_multiplier: number;
  cool_mean_utci: number;
  cool_max_utci: number;
  standard_mean_utci: number;
  standard_max_utci: number;
  cool_duration_seconds: number;
  cool_heat_dose: number;
  scenic_score: number;
  noise_score: number;
  slope_penalty: number;
  route_candidate_count: number;
  graph_source: string;
  utci_source: string | null;
  utci_time: string | null;
  uses_nearest_time: boolean;
  search_truncated: boolean;
  warnings: string[];
};

export type RouteResult = {
  standardRoute: MapCoordinate[];
  coolRoute: MapCoordinate[];
  comparison: RouteComparison;
};

export type TravelMode = 'walk' | 'bike';
export type RouteProfile = 'balanced' | 'coolest' | 'quiet' | 'green' | 'fastest';
export type DeparturePreset = 'now' | 'morning' | 'midday' | 'evening';
export type DetourBudget = 'direct' | 'balanced' | 'explore';

export type RoutePreferences = {
  travelMode: TravelMode;
  profile: RouteProfile;
  departurePreset: DeparturePreset;
  detourBudget: DetourBudget;
  cooling: boolean;
  quiet: boolean;
  scenic: boolean;
  avoidHills: boolean;
  preferFast: boolean;
  showBenches: boolean;
  showWater: boolean;
  maxCandidates: number;
};

export const DEFAULT_ROUTE_PREFERENCES: RoutePreferences = {
  travelMode: 'walk',
  profile: 'balanced',
  departurePreset: 'now',
  detourBudget: 'balanced',
  cooling: false,
  quiet: false,
  scenic: false,
  avoidHills: false,
  preferFast: false,
  showBenches: true,
  showWater: true,
  maxCandidates: 3,
};

type FetchRoutesParams = {
  start: MapCoordinate;
  destination: MapCoordinate;
  preferences?: RoutePreferences;
  thermalPreference?: number;
  slopePreference?: number;
};

type RouteObjective = 'comfort' | 'shortest';

export class RoutingApiError extends Error {
  status?: number;
  detail?: unknown;

  constructor(message: string, status?: number, detail?: unknown) {
    super(message);
    this.name = 'RoutingApiError';
    this.status = status;
    this.detail = detail;
  }
}

const trimTrailingSlash = (value: string) => value.replace(/\/+$/, '');
const DEFAULT_ROUTING_API_PORT = 8010;

export function getRoutingApiBaseUrl(): string {
  const configuredUrl = process.env.EXPO_PUBLIC_ROUTING_API_URL?.trim();
  if (configuredUrl) {
    return trimTrailingSlash(configuredUrl);
  }

  if (Platform.OS === 'android') {
    return `http://10.0.2.2:${DEFAULT_ROUTING_API_PORT}`;
  }
  return `http://127.0.0.1:${DEFAULT_ROUTING_API_PORT}`;
}

function clampPreference(value: number | undefined): number {
  return Math.max(0, Math.min(4, value ?? 0));
}

function legacyPreferences(thermalPreference: number | undefined, slopePreference: number | undefined): RoutePreferences {
  const thermal = clampPreference(thermalPreference ?? 2);
  const slope = clampPreference(slopePreference ?? 2);
  return {
    ...DEFAULT_ROUTE_PREFERENCES,
    profile: thermal >= 3 ? 'coolest' : 'balanced',
    cooling: thermal >= 2,
    avoidHills: slope >= 3,
    detourBudget: thermal >= 3 ? 'explore' : 'balanced',
    maxCandidates: 1,
  };
}

function activePreferences(params: FetchRoutesParams): RoutePreferences {
  return params.preferences ?? legacyPreferences(params.thermalPreference, params.slopePreference);
}

function routeDescriptors(preferences: RoutePreferences): string[] {
  const descriptors = new Set<string>();

  if (preferences.profile === 'coolest') {
    descriptors.add('heat sensitive');
    descriptors.add('shade seeker');
  }
  if (preferences.profile === 'quiet') {
    descriptors.add('noise averse');
  }
  if (preferences.profile === 'green') {
    descriptors.add('scenic');
    descriptors.add('greenery');
  }
  if (preferences.profile === 'fastest') {
    descriptors.add('in a hurry');
    descriptors.add('fastest');
  }

  if (preferences.cooling) {
    descriptors.add('heat sensitive');
    descriptors.add('shade');
  }
  if (preferences.quiet) descriptors.add('quiet');
  if (preferences.scenic) descriptors.add('scenic');
  if (preferences.avoidHills) descriptors.add('avoid hills');
  if (preferences.preferFast) descriptors.add('in a hurry');
  if (preferences.detourBudget === 'explore') descriptors.add('explore');

  return [...descriptors];
}

function roundedWeight(value: number): number {
  return Number(value.toFixed(2));
}

function routeWeights(preferences: RoutePreferences) {
  const byProfile = {
    balanced: {
      weight_cool: 0.35,
      weight_scenic: 0.35,
      weight_quiet: 0.35,
      weight_slope: 0.35,
      weight_time: 1,
      weight_distance: 1,
      uncertainty_penalty: 0.12,
      comfort_threshold: 26,
    },
    coolest: {
      weight_cool: 2.25,
      weight_scenic: 0.7,
      weight_quiet: 0.5,
      weight_slope: 0.45,
      weight_time: 0.15,
      weight_distance: 0.1,
      uncertainty_penalty: 0.32,
      comfort_threshold: 24.5,
    },
    quiet: {
      weight_cool: 1.15,
      weight_scenic: 0.65,
      weight_quiet: 1.8,
      weight_slope: 0.45,
      weight_time: 0.22,
      weight_distance: 0.16,
      uncertainty_penalty: 0.18,
      comfort_threshold: 26,
    },
    green: {
      weight_cool: 0.9,
      weight_scenic: 2.8,
      weight_quiet: 0.7,
      weight_slope: 0.45,
      weight_time: 0.18,
      weight_distance: 0.14,
      uncertainty_penalty: 0.2,
      comfort_threshold: 25.5,
    },
    fastest: {
      weight_cool: 0.65,
      weight_scenic: 0.25,
      weight_quiet: 0.25,
      weight_slope: 0.3,
      weight_time: 1.2,
      weight_distance: 1,
      uncertainty_penalty: 0.08,
      comfort_threshold: 27,
    },
  };

  const weights = { ...byProfile[preferences.profile] };

  if (preferences.cooling && preferences.profile !== 'green') {
    weights.weight_cool = Math.max(weights.weight_cool, 1.9);
    weights.comfort_threshold = Math.min(weights.comfort_threshold, 24.8);
    weights.uncertainty_penalty = Math.max(weights.uncertainty_penalty, 0.28);
  }
  if (preferences.quiet) weights.weight_quiet = Math.max(weights.weight_quiet, 1.5);
  if (preferences.scenic) weights.weight_scenic = Math.max(weights.weight_scenic, 1.25);
  if (preferences.avoidHills) weights.weight_slope = Math.max(weights.weight_slope, 2.2);
  if (preferences.preferFast || preferences.profile === 'fastest') {
    weights.weight_time = Math.max(weights.weight_time, 1.05);
    weights.weight_distance = Math.max(weights.weight_distance, 0.85);
  }

  return Object.fromEntries(
    Object.entries(weights).map(([key, value]) => [key, roundedWeight(value)])
  );
}

function detourRatio(preferences: RoutePreferences): number {
  const base = {
    direct: 0.08,
    balanced: 0.24,
    explore: 0.45,
  }[preferences.detourBudget];

  let ratio = base;
  if (preferences.profile === 'coolest') ratio = Math.max(ratio, 0.32);
  if (preferences.profile === 'fastest' || preferences.preferFast) ratio = Math.min(ratio, 0.16);
  if (preferences.avoidHills) ratio += 0.05;
  return Number(Math.min(ratio, 0.6).toFixed(2));
}

function departureTime(preferences: RoutePreferences): string | undefined {
  const configured = process.env.EXPO_PUBLIC_ROUTING_DEPARTURE_TIME?.trim();
  if (configured && preferences.departurePreset === 'now') {
    return configured;
  }
  if (preferences.departurePreset === 'now') {
    return undefined;
  }

  const date = new Date();
  const hour = {
    morning: 8,
    midday: 14,
    evening: 18,
  }[preferences.departurePreset];
  date.setHours(hour, 0, 0, 0);
  return date.toISOString();
}

function candidateCount(preferences: RoutePreferences): number {
  return Math.max(1, Math.min(5, Math.round(preferences.maxCandidates || 1)));
}

function routeBody(params: FetchRoutesParams, objective: RouteObjective) {
  const preferences = activePreferences(params);
  const resolvedDepartureTime = departureTime(preferences);
  return {
    origin: {
      lat: params.start.latitude,
      lon: params.start.longitude,
    },
    destination: {
      lat: params.destination.latitude,
      lon: params.destination.longitude,
    },
    city: 'Washington, District of Columbia, USA',
    mode: preferences.travelMode,
    objective,
    descriptors: routeDescriptors(preferences),
    weights: routeWeights(preferences),
    detour_ratio: detourRatio(preferences),
    max_candidates: candidateCount(preferences),
    snap_tolerance_m: Math.max(
      params.start.snapToleranceM || 250,
      params.destination.snapToleranceM || 250,
    ),
    ...(resolvedDepartureTime ? { departure_time: resolvedDepartureTime } : {}),
  };
}

function backendMessage(status: number | undefined, payload: unknown): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (detail) {
      return JSON.stringify(detail);
    }
  }
  if (typeof payload === 'string' && payload.trim()) {
    return payload;
  }
  return status ? `Routing backend returned HTTP ${status}.` : 'Routing backend request failed.';
}

async function readResponsePayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function postRoute(baseUrl: string, params: FetchRoutesParams, objective: RouteObjective): Promise<BackendRouteResponse> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}/route`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(routeBody(params, objective)),
    });
  } catch (error) {
    throw new RoutingApiError(
      `Could not reach routing backend at ${baseUrl}. Set EXPO_PUBLIC_ROUTING_API_URL to your computer's LAN address when using Expo Go on a phone.`,
      undefined,
      error
    );
  }

  const payload = await readResponsePayload(response);
  if (!response.ok) {
    throw new RoutingApiError(backendMessage(response.status, payload), response.status, payload);
  }
  return payload as BackendRouteResponse;
}

function toMapCoordinates(geometry: BackendCoordinate[]): MapCoordinate[] {
  return geometry.map((coordinate) => ({
    latitude: coordinate.lat,
    longitude: coordinate.lon,
  }));
}

function firstCandidate(response: BackendRouteResponse, label: string): BackendRouteCandidate {
  const candidate = response.candidates[0];
  if (!candidate) {
    throw new RoutingApiError(`The backend did not return a ${label} route candidate.`);
  }
  return candidate;
}

function shadeMultiplier(standardShadeScore: number, coolShadeScore: number): number {
  if (standardShadeScore <= 0) {
    return 1;
  }
  return Math.max(1, Number((coolShadeScore / standardShadeScore).toFixed(1)));
}

export async function fetchBackendRoutes(params: FetchRoutesParams): Promise<RouteResult> {
  const baseUrl = getRoutingApiBaseUrl();
  const [standardResponse, comfortResponse] = await Promise.all([
    postRoute(baseUrl, params, 'shortest'),
    postRoute(baseUrl, params, 'comfort'),
  ]);

  const standard = firstCandidate(standardResponse, 'standard');
  const cool = firstCandidate(comfortResponse, 'comfort');
  const standardShadeScore = standard.shade_fraction * 100;
  const coolShadeScore = cool.shade_fraction * 100;
  const warnings = [...new Set([...standardResponse.warnings, ...comfortResponse.warnings])];

  return {
    standardRoute: toMapCoordinates(standard.geometry),
    coolRoute: toMapCoordinates(cool.geometry),
    comparison: {
      standard_total_meters: standard.distance_m,
      cool_total_meters: cool.distance_m,
      extra_distance_meters: cool.distance_m - standard.distance_m,
      standard_shade_score: standardShadeScore,
      cool_shade_score: coolShadeScore,
      shade_multiplier: shadeMultiplier(standardShadeScore, coolShadeScore),
      cool_mean_utci: cool.mean_utci,
      cool_max_utci: cool.max_utci,
      standard_mean_utci: standard.mean_utci,
      standard_max_utci: standard.max_utci,
      cool_duration_seconds: cool.duration_s,
      cool_heat_dose: cool.heat_dose,
      scenic_score: cool.scenic_score,
      noise_score: cool.noise_score,
      slope_penalty: cool.slope_penalty,
      route_candidate_count: comfortResponse.candidates.length,
      graph_source: comfortResponse.graph_source,
      utci_source: comfortResponse.utci_source,
      utci_time: comfortResponse.utci_time,
      uses_nearest_time: comfortResponse.uses_nearest_time,
      search_truncated: comfortResponse.search_truncated,
      warnings,
    },
  };
}
