import React, { useState, useEffect, useRef, useMemo } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, Alert, Keyboard, Dimensions, FlatList, ScrollView, useColorScheme } from 'react-native';
import MapView, { Circle, Marker, Polyline, Polygon } from './src/components/MapViewCompat';
import type { Region } from 'react-native-maps';
import BottomSheet, { BottomSheetScrollView } from '@gorhom/bottom-sheet';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { MapPin, Navigation, ChevronLeft, ChevronRight, Layers, LocateFixed, Map as MapIcon, History, X, Clock, Bike, Footprints, Leaf, Volume2, Sun, Moon, Mountain, Armchair, Droplets, Repeat2, Route, Search, Sparkles, ShieldCheck, HeartHandshake, Utensils, House, GraduationCap, ClipboardCheck, Phone } from 'lucide-react-native';
import * as Location from 'expo-location';
import { DEFAULT_ROUTE_PREFERENCES, fetchBackendRoutes, RoutingApiError } from './src/api/routingBackend';
import type { DeparturePreset, DetourBudget, MapCoordinate, RouteComparison, RoutePreferences, RouteProfile, TravelMode } from './src/api/routingBackend';
import { analyzeSupportNotice, SAMPLE_NOTICE } from './src/support/supportAssistant';
import type { SupportCategory, SupportPlan } from './src/support/supportAssistant';
import { calculateRouteProgress, haversineDistanceM } from './src/navigation/navigationMath';
import type { RouteProgress } from './src/navigation/navigationMath';

const INITIAL_REGION = {
  latitude: 38.8895,
  longitude: -76.9833,
  latitudeDelta: 0.05,
  longitudeDelta: 0.05,
};

// Actual bounds of the staged DC graph and climate-data coverage.
const ROUTING_COVERAGE = {
  north: 38.9951111,
  south: 38.8567923,
  west: -77.1172769,
  east: -76.9486223,
};

const BBOX_COORDS = [
  { latitude: ROUTING_COVERAGE.north, longitude: ROUTING_COVERAGE.west },
  { latitude: ROUTING_COVERAGE.north, longitude: ROUTING_COVERAGE.east },
  { latitude: ROUTING_COVERAGE.south, longitude: ROUTING_COVERAGE.east },
  { latitude: ROUTING_COVERAGE.south, longitude: ROUTING_COVERAGE.west },
];

const DARK_MAP_STYLE = [
  { elementType: 'geometry', stylers: [{ color: '#1d2228' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#aeb4bd' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#1d2228' }] },
  { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#4b535d' }] },
  { featureType: 'landscape', elementType: 'geometry', stylers: [{ color: '#20262c' }] },
  { featureType: 'poi', elementType: 'geometry', stylers: [{ color: '#242c31' }] },
  { featureType: 'poi.park', elementType: 'geometry', stylers: [{ color: '#173b2c' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#343b43' }] },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: [{ color: '#252b31' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#4a5058' }] },
  { featureType: 'transit', elementType: 'geometry', stylers: [{ color: '#2b3138' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0e344d' }] },
];

type PlaceSuggestion = {
  place_id: string | number;
  osm_id?: string | number;
  display_name: string;
  lat: string;
  lon: string;
  category?: string;
  type?: string;
  importance?: number;
  canonical?: boolean;
  snap_tolerance_m?: number;
};

type NavigationPhase = 'idle' | 'starting' | 'active' | 'preview';

type SavedDestination = {
  coord: MapCoordinate;
  text: string;
  startCoord?: MapCoordinate;
  standardRoute?: MapCoordinate[];
  coolRoute?: MapCoordinate[];
  comparison?: RouteComparison;
};

const DC_LANDMARKS: Array<PlaceSuggestion & { keywords: string[] }> = [
  {
    place_id: 'dc-white-house',
    display_name: 'The White House, 1600 Pennsylvania Avenue NW, Washington, DC',
    lat: '38.897675',
    lon: '-77.036547',
    category: 'historic',
    type: 'landmark',
    importance: 1,
    canonical: true,
    snap_tolerance_m: 400,
    keywords: ['white house', '1600 pennsylvania', 'president house'],
  },
  {
    place_id: 'dc-us-capitol',
    display_name: 'United States Capitol, First Street SE, Washington, DC',
    lat: '38.889939',
    lon: '-77.009050',
    category: 'historic',
    type: 'landmark',
    importance: 1,
    canonical: true,
    snap_tolerance_m: 400,
    keywords: ['capitol', 'us capitol', 'united states capitol', 'capitol building'],
  },
  {
    place_id: 'dc-union-station',
    display_name: 'Washington Union Station, 50 Massachusetts Avenue NE, Washington, DC',
    lat: '38.897300',
    lon: '-77.006300',
    category: 'railway',
    type: 'station',
    importance: 0.98,
    canonical: true,
    snap_tolerance_m: 400,
    keywords: ['union station', 'washington union station'],
  },
  {
    place_id: 'dc-washington-monument',
    display_name: 'Washington Monument, 2 15th Street NW, Washington, DC',
    lat: '38.889484',
    lon: '-77.035279',
    category: 'historic',
    type: 'monument',
    importance: 0.97,
    canonical: true,
    snap_tolerance_m: 400,
    keywords: ['washington monument', 'monument'],
  },
  {
    place_id: 'dc-lincoln-memorial',
    display_name: 'Lincoln Memorial, 2 Lincoln Memorial Circle NW, Washington, DC',
    lat: '38.889269',
    lon: '-77.050176',
    category: 'historic',
    type: 'memorial',
    importance: 0.97,
    canonical: true,
    snap_tolerance_m: 400,
    keywords: ['lincoln memorial', 'lincoln'],
  },
];

const normalizedSearch = (value: string) => value.toLowerCase().trim().replace(/\s+/g, ' ');

const canonicalLandmarkMatches = (query: string) => {
  const normalized = normalizedSearch(query);
  return DC_LANDMARKS.filter(landmark =>
    landmark.keywords.some(keyword => keyword.startsWith(normalized) || normalized.includes(keyword)),
  );
};

const isInsideRoutingCoverage = (latitude: number, longitude: number) =>
  latitude <= ROUTING_COVERAGE.north && latitude >= ROUTING_COVERAGE.south
  && longitude <= ROUTING_COVERAGE.east && longitude >= ROUTING_COVERAGE.west;

const isLargeLandmarkResult = (item: PlaceSuggestion) => {
  if (item.canonical) return true;
  const tag = `${item.category || ''} ${item.type || ''}`.toLowerCase();
  return /(park|monument|memorial|museum|attraction|historic|government|university|station)/.test(tag);
};

// Zoom threshold: must be zoomed in tighter than this to show POIs
// (Increased to 0.2 because pitched 3D views dramatically inflate longitudeDelta)
const ZOOM_THRESHOLD = 0.2;

// Navigation camera constants
const NAV_PITCH = 65;
const NAV_ALTITUDE = 45;
const DEFAULT_START_COORD = { latitude: 38.8906, longitude: -76.9803 };
const DEFAULT_DESTINATION_COORD = { latitude: 38.8895, longitude: -77.0091 };

const ROUTE_PROFILES: { id: RouteProfile; label: string; sublabel: string }[] = [
  { id: 'balanced', label: 'Balanced', sublabel: 'Comfort + time' },
  { id: 'coolest', label: 'Coolest', sublabel: 'Shade first' },
  { id: 'quiet', label: 'Quiet', sublabel: 'Low traffic' },
  { id: 'green', label: 'Green', sublabel: 'Scenic blocks' },
  { id: 'fastest', label: 'Fast', sublabel: 'Shortest time' },
];

const DEPARTURE_OPTIONS: { id: DeparturePreset; label: string }[] = [
  { id: 'now', label: 'Now' },
  { id: 'morning', label: '8 AM' },
  { id: 'midday', label: '2 PM' },
  { id: 'evening', label: '6 PM' },
];

const DETOUR_OPTIONS: { id: DetourBudget; label: string; sublabel: string }[] = [
  { id: 'direct', label: 'Direct', sublabel: '+8%' },
  { id: 'balanced', label: 'Balanced', sublabel: '+24%' },
  { id: 'explore', label: 'Explore', sublabel: '+45%' },
];

const CANDIDATE_OPTIONS = [1, 3, 5];
const SHEET_COLLAPSED_INDEX = 0;
const SHEET_MID_INDEX = 1;

type SupportFilter = 'all' | SupportCategory;

type SupportResource = {
  id: string;
  name: string;
  category: SupportCategory;
  coordinate: MapCoordinate;
  distanceLabel: string;
  status: string;
  summary: string;
  action: string;
};

const SUPPORT_CATEGORIES: { id: SupportFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'food', label: 'Food' },
  { id: 'housing', label: 'Housing' },
  { id: 'mental', label: 'Mental health' },
  { id: 'school', label: 'School' },
];

// Synthetic demo directory: the UI labels these records and asks users to verify details.
const SUPPORT_RESOURCES: SupportResource[] = [
  {
    id: 'food-pantry',
    name: 'Eastside Family Pantry',
    category: 'food',
    coordinate: { latitude: 38.8898, longitude: -76.9838 },
    distanceLabel: '0.4 mi',
    status: 'Verify hours before going',
    summary: 'Demo listing for groceries, meal-benefit forms, and referrals.',
    action: 'Confirm eligibility and hours',
  },
  {
    id: 'housing-desk',
    name: 'Family Housing Intake Desk',
    category: 'housing',
    coordinate: { latitude: 38.8945, longitude: -76.9905 },
    distanceLabel: '0.8 mi',
    status: 'Human review required',
    summary: 'Demo listing for notice triage, shelter intake, and rental-assistance navigation.',
    action: 'Ask a housing advocate to review the notice',
  },
  {
    id: 'student-wellness',
    name: 'Student Wellness Center',
    category: 'mental',
    coordinate: { latitude: 38.8847, longitude: -76.9788 },
    distanceLabel: '0.6 mi',
    status: 'Ask for same-day support',
    summary: 'Demo listing for counselor referrals and trained safety support.',
    action: 'Talk to a trusted adult or trained counselor',
  },
  {
    id: 'school-success',
    name: 'School Support Office',
    category: 'school',
    coordinate: { latitude: 38.8867, longitude: -76.9958 },
    distanceLabel: '0.9 mi',
    status: 'Verify with the school',
    summary: 'Demo listing for forms, attendance, transportation, and family liaison help.',
    action: 'Bring the complete notice',
  },
];

interface OverpassCoord {
  latitude: number;
  longitude: number;
  id: string;
}

// --- Main Home Screen ---
export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const systemColorScheme = useColorScheme();
  const currentHour = new Date().getHours();
  const automaticDarkMode = systemColorScheme === 'dark' || currentHour < 7 || currentHour >= 19;
  const [themeOverride, setThemeOverride] = useState<'light' | 'dark' | null>(null);
  const isDarkMode = themeOverride ? themeOverride === 'dark' : automaticDarkMode;
  const themeAccent = isDarkMode ? '#8ab4f8' : '#1967d2';
  const themeText = isDarkMode ? '#f1f3f4' : '#202124';
  const themeMuted = isDarkMode ? '#aeb4bd' : '#5f6368';

  const toggleTheme = () => setThemeOverride(isDarkMode ? 'light' : 'dark');

  // Search text state
  const [startText, setStartText] = useState('');
  const [destText, setDestText] = useState('');

  // Coordinate state
  const [startCoord, setStartCoord] = useState<MapCoordinate | null>(null);
  const [destinationCoords, setDestinationCoords] = useState<MapCoordinate | null>(null);

  // Autocomplete
  const [activeField, setActiveField] = useState<'start' | 'dest' | null>(null);
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  // Route state
  const [standardRoute, setStandardRoute] = useState<MapCoordinate[]>([]);
  const [coolRoute, setCoolRoute] = useState<MapCoordinate[]>([]);
  const coolRouteRef = useRef<MapCoordinate[]>([]);
  const [comparison, setComparison] = useState<RouteComparison | null>(null);
  const [loading, setLoading] = useState(false);

  // UI state
  const [isExpanded, setIsExpanded] = useState(false);

  // Map layer toggle
  const [mapType, setMapType] = useState<'standard' | 'satellite'>('standard');

  // Navigation mode
  const [isNavigating, setIsNavigating] = useState(false);
  const isNavigatingRef = useRef(false);
  const [followMode, setFollowMode] = useState(true);
  const followModeRef = useRef(true);
  const [navigationPhase, setNavigationPhase] = useState<NavigationPhase>('idle');
  const [navigationPosition, setNavigationPosition] = useState<MapCoordinate | null>(null);
  const navigationPositionRef = useRef<MapCoordinate | null>(null);
  const [navigationAccuracyM, setNavigationAccuracyM] = useState<number | null>(null);
  const [routeProgress, setRouteProgress] = useState<RouteProgress | null>(null);
  const [originalDestination, setOriginalDestination] = useState<SavedDestination | null>(null);

  // Search History
  const [searchHistory, setSearchHistory] = useState<PlaceSuggestion[]>([]);

  // Crisis-to-action support state
  const [selectedSupportCategory, setSelectedSupportCategory] = useState<SupportFilter>('all');
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>('food-pantry');
  const [supportNoticeText, setSupportNoticeText] = useState('');
  const [supportPlan, setSupportPlan] = useState<SupportPlan | null>(null);

  // User Routing Preferences
  const [routePrefs, setRoutePrefs] = useState<RoutePreferences>(DEFAULT_ROUTE_PREFERENCES);

  // Navigation Heading Tracking
  const headingSubRef = useRef<Location.LocationSubscription | null>(null);
  const locationSubRef = useRef<Location.LocationSubscription | null>(null);
  const navigationSessionRef = useRef(0);
  const navigationStartLockRef = useRef(false);
  const currentHeadingRef = useRef(0);
  const lastCameraUpdateRef = useRef(0);

  // --- Overpass POI state (benches & water fountains) ---
  const [benches, setBenches] = useState<OverpassCoord[]>([]);
  const [waterFountains, setWaterFountains] = useState<OverpassCoord[]>([]);
  const [isZoomedIn, setIsZoomedIn] = useState(false);
  const [fetchingPOIs, setFetchingPOIs] = useState(false);

  const mapRef = useRef<any>(null);
  const homeSheetRef = useRef<BottomSheet>(null);
  const routeSheetRef = useRef<BottomSheet>(null);
  const sheetSnapPoints = useMemo(() => ['16%', '48%', '82%'], []);

  // Track the query text separately to avoid dependency issues
  const [searchQuery, setSearchQuery] = useState('');

  // Debounce timer for Overpass API calls
  const overpassTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const placeSearchAbortRef = useRef<AbortController | null>(null);
  const placeSearchCacheRef = useRef(new Map<string, PlaceSuggestion[]>());

  // --- Combined Overpass API: fetch benches + water in one query ---
  const fetchPOIs = async (region: Region) => {
    const south = Math.max(-90, region.latitude - region.latitudeDelta / 2);
    const west = Math.max(-180, region.longitude - region.longitudeDelta / 2);
    const north = Math.min(90, region.latitude + region.latitudeDelta / 2);
    const east = Math.min(180, region.longitude + region.longitudeDelta / 2);

    // Single query for both benches AND drinking water
    const query = `[out:json][timeout:15];(node["amenity"="bench"](${south},${west},${north},${east});node["amenity"="drinking_water"](${south},${west},${north},${east}););out;`;

    try {
      const encodedQuery = encodeURIComponent(query.trim());
      const response = await fetch(`https://overpass-api.de/api/interpreter?data=${encodedQuery}`, {
        method: 'GET',
        headers: { 'User-Agent': 'ClearHelpDC/1.0', 'Accept': 'application/json' },
      });

      if (response.status === 429) {
        console.warn('[OVERPASS] Rate limited, will retry on next map move');
        return; // Don't clear existing data, just skip this update
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();

      const newBenches: OverpassCoord[] = [];
      const newWater: OverpassCoord[] = [];

      for (const el of data.elements) {
        const coord: OverpassCoord = { id: el.id.toString(), latitude: el.lat, longitude: el.lon };
        if (el.tags?.amenity === 'bench') {
          newBenches.push(coord);
        } else if (el.tags?.amenity === 'drinking_water') {
          newWater.push(coord);
        }
      }

      setBenches(newBenches);
      setWaterFountains(newWater);
      console.log(`[OVERPASS] Loaded ${newBenches.length} benches, ${newWater.length} fountains`);
    } catch (error) {
      console.error('[OVERPASS] Fetch failed:', error);
    }
  };

  // --- Debounced map region change handler ---
  const handleRegionChange = (region: Region) => {
    // If navigation is active, the 3D map pitch creates an artificially massive bounding box
    // centered miles ahead. If we fetch POIs here, it will wipe our local POIs.
    // We already have the POIs we need, so completely bypass fetching.
    if (isNavigatingRef.current) {
      setIsZoomedIn(true);
      return;
    }

    const zoomed = region.longitudeDelta <= ZOOM_THRESHOLD;
    setIsZoomedIn(zoomed);

    // Clear any pending timer
    if (overpassTimerRef.current) clearTimeout(overpassTimerRef.current);

    if (!zoomed) {
      setBenches([]);
      setWaterFountains([]);
      setFetchingPOIs(false);
      return;
    }

    // Debounce: wait 1.5s after user stops panning before hitting API
    setFetchingPOIs(true);
    overpassTimerRef.current = setTimeout(() => {
      fetchPOIs(region).finally(() => setFetchingPOIs(false));
    }, 1500);
  };

  // When the user types, update the search query
  const handleStartChange = (text: string) => {
    setStartText(text);
    setActiveField('start');
    setSearchQuery(text);
  };

  const handleDestChange = (text: string) => {
    setDestText(text);
    setActiveField('dest');
    setSearchQuery(text);
  };

  const updateRoutePref = <K extends keyof RoutePreferences>(key: K, value: RoutePreferences[K]) => {
    setRoutePrefs(prev => ({ ...prev, [key]: value }));
  };

  const selectRouteProfile = (profile: RouteProfile) => {
    setRoutePrefs(prev => ({
      ...prev,
      profile,
      cooling: false,
      quiet: false,
      scenic: false,
      preferFast: false,
    }));
  };

  const toggleRoutePref = (key: 'cooling' | 'quiet' | 'scenic' | 'avoidHills' | 'preferFast' | 'showBenches' | 'showWater') => {
    setRoutePrefs(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const setTravelMode = (mode: TravelMode) => updateRoutePref('travelMode', mode);

  const swapRouteEndpoints = () => {
    setStartText(destText);
    setDestText(startText);
    setStartCoord(destinationCoords);
    setDestinationCoords(startCoord);
    setSuggestions([]);
    setSearchQuery('');
    setActiveField(null);
  };

  const useDemoRoute = () => {
    setStartText('Capitol Hill');
    setStartCoord(DEFAULT_START_COORD);
    setDestText('Union Station');
    setDestinationCoords(DEFAULT_DESTINATION_COORD);
    setSuggestions([]);
    setSearchQuery('');
    setActiveField(null);
    Keyboard.dismiss();
  };

  const useCurrentLocation = async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        Alert.alert('Location unavailable', 'Location permission is needed to use your current position.');
        return;
      }
      const location = await Location.getCurrentPositionAsync({});
      const coord = {
        latitude: location.coords.latitude,
        longitude: location.coords.longitude,
      };
      setStartCoord(coord);
      setStartText('Current location');
      setSuggestions([]);
      setSearchQuery('');
      setActiveField(null);
      Keyboard.dismiss();
    } catch (error) {
      console.warn('Current location failed:', error);
      Alert.alert('Location unavailable', 'Could not read your current position.');
    }
  };

  const visibleSupportResources = useMemo(
    () => SUPPORT_RESOURCES.filter(resource => selectedSupportCategory === 'all' || resource.category === selectedSupportCategory),
    [selectedSupportCategory],
  );

  const selectedResource = useMemo(
    () => SUPPORT_RESOURCES.find(resource => resource.id === selectedResourceId) || visibleSupportResources[0],
    [selectedResourceId, visibleSupportResources],
  );

  const selectSupportCategory = (category: SupportFilter) => {
    setSelectedSupportCategory(category);
    const firstMatch = SUPPORT_RESOURCES.find(resource => category === 'all' || resource.category === category);
    if (firstMatch) setSelectedResourceId(firstMatch.id);
  };

  const focusSupportResource = (resource: SupportResource) => {
    setSelectedResourceId(resource.id);
    setSelectedSupportCategory(resource.category);
    mapRef.current?.animateToRegion(
      {
        latitude: resource.coordinate.latitude,
        longitude: resource.coordinate.longitude,
        latitudeDelta: 0.018,
        longitudeDelta: 0.018,
      },
      500,
    );
  };

  const buildSupportPlan = () => {
    const notice = supportNoticeText.trim() || SAMPLE_NOTICE;
    setSupportNoticeText(notice);
    const plan = analyzeSupportNotice(notice);
    setSupportPlan(plan);
    if (plan.confidence === 'Needs review') {
      homeSheetRef.current?.snapToIndex(SHEET_MID_INDEX);
      return;
    }
    selectSupportCategory(plan.category);
    const matchingResource = SUPPORT_RESOURCES.find(resource => resource.category === plan.category);
    if (matchingResource) focusSupportResource(matchingResource);
    homeSheetRef.current?.snapToIndex(SHEET_MID_INDEX);
  };

  const routeToSupportResource = (resource: SupportResource) => {
    const activeStart = startCoord || DEFAULT_START_COORD;
    if (!startCoord && !startText) {
      setStartText('Current area');
      setStartCoord(activeStart);
    }
    setDestinationCoords(resource.coordinate);
    setDestText(resource.name);
    focusSupportResource(resource);
    fetchDualRoute(activeStart, resource.coordinate);
  };

  const contactSupportResource = (resource: SupportResource) => {
    Alert.alert(
      'Demo directory - verify first',
      `${resource.name} is a synthetic prototype listing. In a deployed version, this action opens a verified official number. ${resource.action}.`,
    );
  };

  // Debounced search effect keyed on searchQuery
  useEffect(() => {
    const normalizedQuery = normalizedSearch(searchQuery);
    if (normalizedQuery.length < 2) {
      placeSearchAbortRef.current?.abort();
      setSuggestions([]);
      setIsSearching(false);
      return;
    }

    const cached = placeSearchCacheRef.current.get(normalizedQuery);
    if (cached) {
      setSuggestions(cached);
      setIsSearching(false);
      return;
    }

    const canonicalMatches = canonicalLandmarkMatches(normalizedQuery);
    setSuggestions(canonicalMatches);

    const timeoutId = setTimeout(async () => {
      console.log('[SEARCH] Fetching results for:', searchQuery);
      placeSearchAbortRef.current?.abort();
      const controller = new AbortController();
      placeSearchAbortRef.current = controller;
      setIsSearching(true);
      try {
        const viewbox = `${ROUTING_COVERAGE.west},${ROUTING_COVERAGE.north},${ROUTING_COVERAGE.east},${ROUTING_COVERAGE.south}`;
        const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(searchQuery)}&format=jsonv2&viewbox=${viewbox}&bounded=1&countrycodes=us&addressdetails=1&namedetails=1&dedupe=1&limit=10`;
        const response = await fetch(url, {
          headers: { 'User-Agent': 'ClearHelpDC/1.0', 'Accept-Language': 'en' },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Place search returned HTTP ${response.status}`);
        const data = await response.json() as PlaceSuggestion[];

        const queryTokens = normalizedQuery.split(' ');
        const scored = (Array.isArray(data) ? data : [])
          .filter(item => isInsideRoutingCoverage(Number(item.lat), Number(item.lon)))
          .map(item => {
            const label = normalizedSearch(item.display_name);
            const primary = normalizedSearch(item.display_name.split(',')[0]);
            let relevance = (Number(item.importance) || 0) * 10;
            if (primary === normalizedQuery) relevance += 80;
            else if (primary.startsWith(normalizedQuery)) relevance += 60;
            else if (primary.includes(normalizedQuery)) relevance += 40;
            if (queryTokens.every(token => label.includes(token))) relevance += 20;
            return {
              ...item,
              snap_tolerance_m: isLargeLandmarkResult(item) ? 400 : undefined,
              relevance,
            };
          });

        const merged = [
          ...canonicalMatches.map(item => ({ ...item, relevance: 200 })),
          ...scored,
        ].sort((a, b) => b.relevance - a.relevance);

        const seen = new Set<string>();
        const ranked = merged.filter(item => {
          const key = `${normalizedSearch(item.display_name.split(',')[0])}|${Number(item.lat).toFixed(4)}|${Number(item.lon).toFixed(4)}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        }).slice(0, 8).map(({ relevance: _relevance, ...item }) => item);

        console.log('[SEARCH] Got', ranked.length, 'ranked results');
        placeSearchCacheRef.current.set(normalizedQuery, ranked);
        setSuggestions(ranked);
      } catch (error: any) {
        if (error?.name !== 'AbortError') {
          console.error('[SEARCH] Error:', error);
          setSuggestions(canonicalMatches);
        }
      } finally {
        if (placeSearchAbortRef.current === controller) setIsSearching(false);
      }
    }, 250);

    return () => {
      clearTimeout(timeoutId);
      placeSearchAbortRef.current?.abort();
    };
  }, [searchQuery]);

  const handleSuggestionPress = (item: PlaceSuggestion) => {
    const shortName = item.display_name.split(',')[0];
    const coord: MapCoordinate = {
      latitude: parseFloat(item.lat),
      longitude: parseFloat(item.lon),
      snapToleranceM: item.snap_tolerance_m || (isLargeLandmarkResult(item) ? 400 : undefined),
    };

    if (activeField === 'start') {
      setStartText(shortName);
      setStartCoord(coord);
    } else {
      setDestText(shortName);
      setDestinationCoords(coord);
    }

    // Update Search History (keep last 10, unique)
    setSearchHistory(prev => {
      const filtered = prev.filter(h => h.place_id !== item.place_id && h.display_name !== item.display_name);
      return [item, ...filtered].slice(0, 10);
    });

    setSuggestions([]);
    setSearchQuery('');
    setActiveField(null);
    Keyboard.dismiss();
  };

  const fetchDualRoute = async (customStart?: MapCoordinate, customDest?: MapCoordinate) => {
    let activeStart = customStart || startCoord;
    let activeEnd = customDest || destinationCoords;

    if (!activeStart || !activeEnd) {
      activeStart = DEFAULT_START_COORD;
      activeEnd = DEFAULT_DESTINATION_COORD;
    }

    setLoading(true);
    Keyboard.dismiss();
    setIsExpanded(false);
    setSuggestions([]);
    setSearchQuery('');
    setActiveField(null);

    try {
      const data = await fetchBackendRoutes({
        start: activeStart,
        destination: activeEnd,
        preferences: routePrefs,
      });

      setStandardRoute(data.standardRoute);
      setCoolRoute(data.coolRoute);
      coolRouteRef.current = data.coolRoute;
      setComparison(data.comparison);

      if (isNavigatingRef.current && navigationPositionRef.current && data.coolRoute.length > 1) {
        setRouteProgress(calculateRouteProgress(data.coolRoute, navigationPositionRef.current));
      }

      if (data.coolRoute.length > 0) {
        if (isNavigatingRef.current && followModeRef.current) {
          mapRef.current?.animateCamera(
            {
              center: navigationPositionRef.current || { latitude: activeStart.latitude, longitude: activeStart.longitude },
              pitch: NAV_PITCH,
              heading: currentHeadingRef.current,
              altitude: NAV_ALTITUDE,
            },
            { duration: 600 }
          );
        } else {
          mapRef.current?.fitToCoordinates(data.coolRoute, {
            edgePadding: { top: 120, right: 60, bottom: Dimensions.get('window').height * 0.5, left: 60 },
            animated: true,
          });
        }
      }

      if (!isNavigatingRef.current) {
        routeSheetRef.current?.snapToIndex(SHEET_MID_INDEX);
      }
      return true;
    } catch (err: any) {
      console.error(err);
      const message = err instanceof RoutingApiError
        ? err.message
        : err.message || "Could not calculate routes. Please try different locations.";
      Alert.alert("Route Error", message);
      if (!isNavigatingRef.current) setComparison(null);
      return false;
    } finally {
      setLoading(false);
    }
  };

  // --- Navigation Mode ---
  const stopNavigationSensors = () => {
    headingSubRef.current?.remove();
    headingSubRef.current = null;
    locationSubRef.current?.remove();
    locationSubRef.current = null;
  };

  useEffect(() => () => {
    navigationSessionRef.current += 1;
    isNavigatingRef.current = false;
    headingSubRef.current?.remove();
    locationSubRef.current?.remove();
  }, []);

  const setLiveNavigationPosition = (position: MapCoordinate, sessionId: number, accuracyM?: number | null) => {
    if (!isNavigatingRef.current || navigationSessionRef.current !== sessionId) return;
    navigationPositionRef.current = position;
    setNavigationPosition(position);
    if (typeof accuracyM === 'number') setNavigationAccuracyM(accuracyM);
    const activeRoute = coolRouteRef.current;
    if (activeRoute.length > 1) setRouteProgress(calculateRouteProgress(activeRoute, position));

    const now = Date.now();
    if (followModeRef.current && now - lastCameraUpdateRef.current >= 350) {
      lastCameraUpdateRef.current = now;
      mapRef.current?.animateCamera(
        {
          center: position,
          pitch: NAV_PITCH,
          heading: currentHeadingRef.current,
          altitude: NAV_ALTITUDE,
        },
        { duration: 300 },
      );
    }
  };

  const initializeNavigationSensors = async (sessionId: number, routeStart: MapCoordinate) => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (!isNavigatingRef.current || navigationSessionRef.current !== sessionId) return;
      if (status !== 'granted') {
        setNavigationPhase('preview');
        return;
      }

      // Start compass tracking immediately so rotating the phone rotates the map,
      // even if GPS is still resolving or the route is being previewed remotely.
      try {
        const headingSubscription = await Location.watchHeadingAsync(heading => {
          if (!isNavigatingRef.current || navigationSessionRef.current !== sessionId) return;
          const nextHeading = heading.trueHeading >= 0 ? heading.trueHeading : heading.magHeading;
          currentHeadingRef.current = nextHeading;
          const now = Date.now();
          if (followModeRef.current && navigationPositionRef.current && now - lastCameraUpdateRef.current >= 250) {
            lastCameraUpdateRef.current = now;
            mapRef.current?.animateCamera(
              { center: navigationPositionRef.current, pitch: NAV_PITCH, heading: nextHeading, altitude: NAV_ALTITUDE },
              { duration: 180 },
            );
          }
        });
        if (!isNavigatingRef.current || navigationSessionRef.current !== sessionId) {
          headingSubscription.remove();
          return;
        }
        headingSubRef.current = headingSubscription;
      } catch (headingError) {
        // GPS following remains useful when a device lacks a heading sensor.
        console.warn('Heading sensor unavailable; continuing with north-up GPS:', headingError);
      }

      const initialLocation = await Promise.race([
        Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }),
        new Promise<never>((_resolve, reject) => {
          setTimeout(() => reject(new Error('Timed out while acquiring the initial GPS position.')), 6_000);
        }),
      ]);
      if (!isNavigatingRef.current || navigationSessionRef.current !== sessionId) return;
      const livePosition = {
        latitude: initialLocation.coords.latitude,
        longitude: initialLocation.coords.longitude,
      };

      // A typed route can be previewed from anywhere, but live GPS following only starts
      // when the phone is reasonably close to the selected route origin.
      if (haversineDistanceM(livePosition, routeStart) > 1_500) {
        setNavigationPhase('preview');
        return;
      }

      setNavigationPhase('active');
      setLiveNavigationPosition(livePosition, sessionId, initialLocation.coords.accuracy);

      const locationSubscription = await Location.watchPositionAsync(
        {
          accuracy: Location.Accuracy.BestForNavigation,
          distanceInterval: 3,
          timeInterval: 1000,
        },
        location => {
          setLiveNavigationPosition(
            { latitude: location.coords.latitude, longitude: location.coords.longitude },
            sessionId,
            location.coords.accuracy,
          );
        },
      );
      if (!isNavigatingRef.current || navigationSessionRef.current !== sessionId) {
        locationSubscription.remove();
        return;
      }
      locationSubRef.current = locationSubscription;
    } catch (error) {
      if (isNavigatingRef.current && navigationSessionRef.current === sessionId) {
        console.warn('Live navigation sensors unavailable:', error);
        setNavigationPhase('preview');
      }
    } finally {
      if (navigationSessionRef.current === sessionId) navigationStartLockRef.current = false;
    }
  };

  const startNavigation = () => {
    const activeRoute = coolRouteRef.current.length > 0 ? coolRouteRef.current : coolRoute;
    const routeStart = activeRoute[0] || startCoord;
    if (!routeStart || activeRoute.length < 2 || navigationStartLockRef.current || isNavigatingRef.current) return;

    navigationStartLockRef.current = true;
    const sessionId = navigationSessionRef.current + 1;
    navigationSessionRef.current = sessionId;
    isNavigatingRef.current = true;
    followModeRef.current = true;
    navigationPositionRef.current = routeStart;
    currentHeadingRef.current = 0;
    lastCameraUpdateRef.current = Date.now();

    // Enter navigation immediately; permissions and sensors initialize afterward.
    setIsNavigating(true);
    setNavigationPhase('starting');
    setFollowMode(true);
    setNavigationPosition(routeStart);
    setNavigationAccuracyM(null);
    setRouteProgress(calculateRouteProgress(activeRoute, routeStart));
    routeSheetRef.current?.close();
    mapRef.current?.animateCamera(
      { center: routeStart, pitch: NAV_PITCH, heading: 0, altitude: NAV_ALTITUDE },
      { duration: 350 },
    );

    void initializeNavigationSensors(sessionId, routeStart);
  };

  const exitNavigation = () => {
    const exitSessionId = navigationSessionRef.current + 1;
    navigationSessionRef.current = exitSessionId;
    navigationStartLockRef.current = false;
    isNavigatingRef.current = false;
    followModeRef.current = true;
    stopNavigationSensors();

    setIsNavigating(false);
    setNavigationPhase('idle');
    setFollowMode(true);
    setNavigationPosition(null);
    setNavigationAccuracyM(null);
    navigationPositionRef.current = null;
    setRouteProgress(null);

    mapRef.current?.animateCamera({ pitch: 0, heading: 0, altitude: 5000 }, { duration: 400 });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (navigationSessionRef.current !== exitSessionId) return;
      if (coolRouteRef.current.length > 1) {
        mapRef.current?.fitToCoordinates(coolRouteRef.current, {
          edgePadding: { top: 120, right: 60, bottom: Dimensions.get('window').height * 0.5, left: 60 },
          animated: true,
        });
      }
      routeSheetRef.current?.snapToIndex(SHEET_MID_INDEX);
    }));
  };

  const toggleFollowMode = () => {
    if (!isNavigatingRef.current) return;
    const nextFollowMode = !followModeRef.current;
    followModeRef.current = nextFollowMode;
    setFollowMode(nextFollowMode);
    if (nextFollowMode) {
      const center = navigationPositionRef.current || coolRouteRef.current[0] || startCoord;
      if (center) {
        mapRef.current?.animateCamera(
          { center, pitch: NAV_PITCH, heading: currentHeadingRef.current, altitude: NAV_ALTITUDE },
          { duration: 350 },
        );
      }
    } else {
      mapRef.current?.animateCamera({ pitch: 0, heading: 0, altitude: 2000 }, { duration: 350 });
    }
  };

  const handleMapDrag = () => {
    if (isNavigatingRef.current && followModeRef.current) {
      followModeRef.current = false;
      setFollowMode(false);
    }
  };

  const handleDetour = async (type: 'bench' | 'water') => {
    const pois = type === 'bench' ? benches : waterFountains;
    if (pois.length === 0) {
      Alert.alert("No Data", `No ${type}s loaded in this area. Try zooming out slightly to load POIs.`);
      return;
    }

    // Switch to 2D bird's-eye view automatically
    if (followModeRef.current) {
      followModeRef.current = false;
      setFollowMode(false);
      mapRef.current?.animateCamera(
        { pitch: 0, heading: 0, altitude: 2000 },
        { duration: 600 }
      );
    }

    // Prefer live GPS progress; route origin is only a preview fallback.
    const currentLoc = navigationPositionRef.current
      || coolRouteRef.current[0]
      || startCoord
      || { latitude: 38.8906, longitude: -76.9803 };
    // Safe extraction of destination coordinates
    let destLoc = destinationCoords;
    if (originalDestination && originalDestination.coord) {
       destLoc = originalDestination.coord;
    }
    if (!destLoc) destLoc = currentLoc;

    let bestPoi = pois[0];
    let bestScore = Infinity;

    // We want to minimize (Distance from Us) + 0.5 * (Distance to Destination)
    // This creates an ellipse of preferred POIs in front of the user towards the goal.
    pois.forEach(p => {
      // rough euclidian is fine for local distances
      const dFromUs = Math.sqrt(Math.pow(p.latitude - currentLoc.latitude, 2) + Math.pow(p.longitude - currentLoc.longitude, 2));
      const dToDest = Math.sqrt(Math.pow(p.latitude - destLoc.latitude, 2) + Math.pow(p.longitude - destLoc.longitude, 2));

      const score = dFromUs + (0.5 * dToDest);
      if (score < bestScore) {
        bestScore = score;
        bestPoi = p;
      }
    });

    // Save original destination if not already saved
    const savedDestination = originalDestination
      || (destinationCoords ? {
        coord: destinationCoords,
        text: destText,
        startCoord: coolRouteRef.current[0] || startCoord || undefined,
        standardRoute: [...standardRoute],
        coolRoute: [...coolRouteRef.current],
        comparison: comparison || undefined,
      } : null);
    if (!originalDestination && savedDestination) setOriginalDestination(savedDestination);

    const newDest = { latitude: bestPoi.latitude, longitude: bestPoi.longitude };
    setDestinationCoords(newDest);
    setDestText(`${type === 'bench' ? 'Rest Bench' : 'Water Fountain'}`);

    // Re-fetch from live progress rather than restarting at the original origin.
    const updated = await fetchDualRoute(currentLoc, newDest);
    if (!updated && savedDestination) {
      setDestinationCoords(savedDestination.coord);
      setDestText(savedDestination.text);
      if (!originalDestination) setOriginalDestination(null);
    }
  };

  const handleResumeJourney = async () => {
    if (!originalDestination) return;
    const savedDestination = originalDestination;
    const resumed = await fetchDualRoute(
      navigationPositionRef.current || startCoord || undefined,
      savedDestination.coord,
    );
    if (resumed) {
      setDestinationCoords(savedDestination.coord);
      setDestText(savedDestination.text);
      setOriginalDestination(null);
    }
  };

  const handleCloseRoutePanel = () => {
    routeSheetRef.current?.snapToIndex(SHEET_COLLAPSED_INDEX);
    if (!originalDestination) return;

    const savedJourney = originalDestination;
    setDestinationCoords(savedJourney.coord);
    setDestText(savedJourney.text);

    if (savedJourney.standardRoute && savedJourney.coolRoute && savedJourney.comparison) {
      setStandardRoute(savedJourney.standardRoute);
      setCoolRoute(savedJourney.coolRoute);
      coolRouteRef.current = savedJourney.coolRoute;
      setComparison(savedJourney.comparison);
      setOriginalDestination(null);

      requestAnimationFrame(() => {
        if (savedJourney.coolRoute && savedJourney.coolRoute.length > 1) {
          mapRef.current?.fitToCoordinates(savedJourney.coolRoute, {
            edgePadding: { top: 120, right: 60, bottom: Dimensions.get('window').height * 0.28, left: 60 },
            animated: true,
          });
        }
      });
      return;
    }

    // Fallback for a route created before the snapshot fields were available.
    void fetchDualRoute(savedJourney.startCoord || startCoord || undefined, savedJourney.coord).then(restored => {
      if (restored) {
        setOriginalDestination(null);
        routeSheetRef.current?.snapToIndex(SHEET_COLLAPSED_INDEX);
      }
    });
  };

  const hasSuggestions = suggestions.length > 0;
  const enabledPoiLabel = routePrefs.showBenches && routePrefs.showWater
    ? 'benches & water'
    : routePrefs.showBenches
      ? 'benches'
      : routePrefs.showWater
        ? 'water'
        : '';
  const floatingControlBottom = insets.bottom + 80;
  const remainingDistanceM = routeProgress?.remainingDistanceM ?? comparison?.cool_total_meters ?? 0;
  const remainingDurationSeconds = comparison
    ? comparison.cool_duration_seconds * (routeProgress ? 1 - routeProgress.fractionComplete : 1)
    : 0;
  const isGpsWeak = navigationPhase === 'active' && navigationAccuracyM !== null && navigationAccuracyM > 65;
  const isOffRoute = navigationPhase === 'active' && !isGpsWeak && Boolean(routeProgress && routeProgress.distanceFromRouteM > 60);
  const isArriving = navigationPhase === 'active' && remainingDistanceM <= 25;
  const navigationStatusText = navigationPhase === 'starting'
    ? 'Starting GPS…'
      : isArriving
        ? 'You have arrived'
      : isGpsWeak
        ? 'GPS signal is weak · move into a more open area'
      : isOffRoute
        ? 'Off route · return to the highlighted line'
        : followMode
          ? 'Live guidance · following your position'
          : 'Map unlocked · tap recenter to follow';

  const renderProfileIcon = (profile: RouteProfile, color: string) => {
    if (profile === 'coolest') return <Sun size={17} color={color} />;
    if (profile === 'quiet') return <Volume2 size={17} color={color} />;
    if (profile === 'green') return <Leaf size={17} color={color} />;
    if (profile === 'fastest') return <Navigation size={17} color={color} />;
    return <Route size={17} color={color} />;
  };

  const renderSupportIcon = (category: SupportCategory, color: string, size = 17) => {
    if (category === 'food') return <Utensils size={size} color={color} />;
    if (category === 'housing') return <House size={size} color={color} />;
    if (category === 'mental') return <HeartHandshake size={size} color={color} />;
    return <GraduationCap size={size} color={color} />;
  };

  return (
    <View style={styles.container}>
      {/* ---- Full-Screen Map ---- */}
      <MapView
        ref={mapRef}
        style={styles.map}
        initialRegion={INITIAL_REGION}
        mapType={mapType}
        customMapStyle={isDarkMode && mapType === 'standard' ? DARK_MAP_STYLE : []}
        userInterfaceStyle={isDarkMode ? 'dark' : 'light'}
        showsUserLocation={!isNavigating}
        onRegionChangeComplete={handleRegionChange}
        onPanDrag={handleMapDrag}
        pitchEnabled={true}
        rotateEnabled={true}
      >
        {/* Persistent Operating Boundary Box */}
        <Polygon
          coordinates={BBOX_COORDS}
          strokeColor="rgba(11, 87, 208, 0.20)"
          strokeWidth={2}
          lineDashPattern={[6, 8]}
          fillColor="rgba(11, 87, 208, 0.025)"
        />

        {!isNavigating && visibleSupportResources.map(resource => {
          const isSelected = selectedResource?.id === resource.id;
          return (
            <Marker
              key={resource.id}
              coordinate={resource.coordinate}
              tracksViewChanges={false}
              onPress={() => focusSupportResource(resource)}
            >
              <View style={[styles.supportMarker, isSelected && styles.supportMarkerSelected]}>
                {renderSupportIcon(resource.category, isSelected ? '#fff' : '#1967d2', 18)}
              </View>
            </Marker>
          );
        })}

        {/* Standard Route (solid red) */}
        {standardRoute.length > 0 && (
          <Polyline coordinates={standardRoute} strokeColor="#7c8798" strokeWidth={5} />
        )}
        {/* Cool Route (solid blue) */}
        {coolRoute.length > 0 && (
          <Polyline coordinates={coolRoute} strokeColor="#0b57d0" strokeWidth={7} />
        )}
        {/* Route start/end markers */}
        {coolRoute.length > 0 && (
          <>
            {!isNavigating && <Marker coordinate={coolRoute[0]} pinColor="green" title="Start" />}
            <Marker coordinate={coolRoute[coolRoute.length - 1]} pinColor="red" title="End" />
          </>
        )}

        {/* ---- Live user position (route origin in preview mode) ---- */}
        {isNavigating && navigationPosition && (
          <Marker coordinate={navigationPosition} anchor={{ x: 0.5, y: 0.5 }}>
            <View style={styles.userDotWrap}>
              <View style={styles.userDotHalo} />
              <View style={styles.userDotLine} />
              <View style={styles.userDotCenter} />
            </View>
          </Marker>
        )}

        {/* ---- Bench Markers ---- */}
        {routePrefs.showBenches && isZoomedIn && benches.map((bench) => (
          <React.Fragment key={`bench-${bench.id}`}>
            <Circle
              center={bench}
              radius={4}
              strokeColor="rgba(26, 115, 232, 0.6)"
              fillColor="rgba(26, 115, 232, 0.2)"
            />
            <Marker coordinate={bench} tracksViewChanges={false}>
              <View style={styles.benchMarker}>
                <Text style={styles.poiEmoji}>🪑</Text>
              </View>
            </Marker>
          </React.Fragment>
        ))}

        {/* ---- Water Fountain Markers ---- */}
        {routePrefs.showWater && isZoomedIn && waterFountains.map((water) => (
          <React.Fragment key={`water-${water.id}`}>
            <Circle
              center={water}
              radius={4}
              strokeColor="rgba(33, 150, 243, 0.6)"
              fillColor="rgba(33, 150, 243, 0.2)"
            />
            <Marker coordinate={water} tracksViewChanges={false}>
              <View style={styles.waterMarker}>
                <Text style={styles.poiEmoji}>💧</Text>
              </View>
            </Marker>
          </React.Fragment>
        ))}
      </MapView>

      {/* ---- POI Status Pill ---- */}
      {!isExpanded && !isNavigating && enabledPoiLabel.length > 0 && (
        <View style={[styles.poiStatusWrap, { top: insets.top + 70 }]} pointerEvents="none">
          {fetchingPOIs && (
            <View style={styles.poiPill}>
              <ActivityIndicator size="small" color="#4285f4" />
              <Text style={styles.poiPillText}> Loading {enabledPoiLabel}...</Text>
            </View>
          )}
          {!isZoomedIn && !fetchingPOIs && (
            <View style={styles.poiPill}>
              <Text style={styles.poiPillText}>Zoom in for {enabledPoiLabel}</Text>
            </View>
          )}
        </View>
      )}

      {/* ---- Top Search UI ---- */}
      {isNavigating ? null : !isExpanded ? (
        /* -- Collapsed bar -- */
        <TouchableOpacity
          style={[styles.collapsedBar, isDarkMode && styles.collapsedBarDark, { top: insets.top + 10 }]}
          onPress={() => setIsExpanded(true)}
          activeOpacity={0.9}
        >
          <View style={styles.collapsedInner}>
            <View style={styles.appIcon}>
              <HeartHandshake size={18} color="#fff" />
            </View>
            <Text style={[styles.collapsedText, isDarkMode && styles.textDark]}>Search help near you</Text>
            <TouchableOpacity
              style={[styles.themeToggle, isDarkMode && styles.themeToggleDark]}
              onPress={(event) => { event.stopPropagation(); toggleTheme(); }}
              accessibilityLabel={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
              activeOpacity={0.75}
            >
              {isDarkMode ? <Sun size={17} color="#fdd663" /> : <Moon size={17} color="#5f6368" />}
            </TouchableOpacity>
          </View>
        </TouchableOpacity>
      ) : (
        /* -- Expanded full-screen search overlay -- */
        <View style={[styles.expandedOverlay, isDarkMode && styles.expandedOverlayDark, { paddingTop: insets.top + 10 }]}>
          <View style={[styles.expandedCard, isDarkMode && styles.surfaceDark]}>
            <View style={styles.directionsHeader}>
              <TouchableOpacity
                onPress={() => { setIsExpanded(false); setSuggestions([]); setSearchQuery(''); setActiveField(null); }}
                style={styles.backBtn}
              >
                <ChevronLeft size={24} color={themeText} />
              </TouchableOpacity>
              <Text style={[styles.directionsTitle, isDarkMode && styles.textDark]}>Directions</Text>
              <TouchableOpacity onPress={toggleTheme} style={[styles.headerIconBtn, isDarkMode && styles.headerIconBtnDark]} activeOpacity={0.75}>
                {isDarkMode ? <Sun size={18} color="#fdd663" /> : <Moon size={18} color="#5f6368" />}
              </TouchableOpacity>
              <TouchableOpacity onPress={swapRouteEndpoints} style={[styles.headerIconBtn, isDarkMode && styles.headerIconBtnDark]} activeOpacity={0.75}>
                <Repeat2 size={19} color={themeMuted} />
              </TouchableOpacity>
            </View>

            <View style={styles.expandedRow}>
              <View style={styles.inputsCol}>
                <View style={[styles.fieldRow, isDarkMode && styles.fieldRowDark, activeField === 'start' && styles.fieldRowActive, activeField === 'start' && isDarkMode && styles.fieldRowActiveDark]}>
                  <View style={styles.dotBlue} />
                  <TextInput
                    placeholder="Starting point"
                    placeholderTextColor={isDarkMode ? '#858c96' : '#9aa0a6'}
                    selectionColor={themeAccent}
                    style={[styles.fieldInput, isDarkMode && styles.textDark]}
                    value={startText}
                    onChangeText={handleStartChange}
                    onFocus={() => { setActiveField('start'); if (startText.length > 2) setSearchQuery(startText); }}
                    returnKeyType="next"
                    autoFocus={true}
                  />
                  {activeField === 'start' && isSearching && <ActivityIndicator size="small" color="#4285f4" />}
                </View>

                <View style={styles.fieldDivider} />

                {/* Destination field */}
                <View style={[styles.fieldRow, isDarkMode && styles.fieldRowDark, activeField === 'dest' && styles.fieldRowActive, activeField === 'dest' && isDarkMode && styles.fieldRowActiveDark]}>
                  <View style={styles.dotRed} />
                  <TextInput
                    placeholder="Destination"
                    placeholderTextColor={isDarkMode ? '#858c96' : '#9aa0a6'}
                    selectionColor={themeAccent}
                    style={[styles.fieldInput, isDarkMode && styles.textDark]}
                    value={destText}
                    onChangeText={handleDestChange}
                    onFocus={() => { setActiveField('dest'); if (destText.length > 2) setSearchQuery(destText); }}
                    returnKeyType="search"
                  />
                  {activeField === 'dest' && isSearching && <ActivityIndicator size="small" color="#4285f4" />}
                </View>
              </View>
            </View>

            <View style={styles.travelModeTabs}>
              <TouchableOpacity
                style={[styles.travelModeTab, isDarkMode && styles.controlSurfaceDark, routePrefs.travelMode === 'walk' && styles.travelModeTabActive, routePrefs.travelMode === 'walk' && isDarkMode && styles.controlActiveDark]}
                onPress={() => setTravelMode('walk')}
                activeOpacity={0.75}
              >
                <Footprints size={18} color={routePrefs.travelMode === 'walk' ? themeAccent : themeMuted} />
                <Text style={[styles.travelModeText, isDarkMode && styles.mutedTextDark, routePrefs.travelMode === 'walk' && styles.travelModeTextActive, routePrefs.travelMode === 'walk' && isDarkMode && styles.accentTextDark]}>Walk</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.travelModeTab, isDarkMode && styles.controlSurfaceDark, routePrefs.travelMode === 'bike' && styles.travelModeTabActive, routePrefs.travelMode === 'bike' && isDarkMode && styles.controlActiveDark]}
                onPress={() => setTravelMode('bike')}
                activeOpacity={0.75}
              >
                <Bike size={18} color={routePrefs.travelMode === 'bike' ? themeAccent : themeMuted} />
                <Text style={[styles.travelModeText, isDarkMode && styles.mutedTextDark, routePrefs.travelMode === 'bike' && styles.travelModeTextActive, routePrefs.travelMode === 'bike' && isDarkMode && styles.accentTextDark]}>Bike</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Suggestions or History list */}
          {(hasSuggestions || (searchHistory.length > 0 && activeField)) ? (
            <View style={[styles.suggestionsPanel, isDarkMode && styles.suggestionsPanelDark]}>
              <FlatList
                data={hasSuggestions ? suggestions : searchHistory}
                keyExtractor={(item, i) => String(item.place_id || item.osm_id || i)}
                keyboardShouldPersistTaps="always"
                style={styles.suggestionsList}
                contentContainerStyle={styles.suggestionsContent}
                ItemSeparatorComponent={() => <View style={[styles.suggestionDivider, isDarkMode && styles.suggestionDividerDark]} />}
                renderItem={({ item }) => {
                  const primaryName = item.display_name.split(',')[0];
                  const secondaryName = item.display_name.split(',').slice(1).join(',').trim();
                  return (
                    <TouchableOpacity
                      style={[styles.suggestionRow, isDarkMode && styles.suggestionRowDark]}
                      onPress={() => handleSuggestionPress(item)}
                      activeOpacity={0.65}
                    >
                      <View style={[styles.suggestionIcon, isDarkMode && styles.suggestionIconDark]}>
                        {hasSuggestions ? <MapPin size={18} color={themeAccent} /> : <History size={18} color={themeMuted} />}
                      </View>
                      <View style={styles.suggestionTextCol}>
                        <View style={styles.suggestionTitleRow}>
                          <Text style={[styles.suggestionMain, isDarkMode && styles.textDark]} numberOfLines={1}>
                            {primaryName}
                          </Text>
                          {item.canonical && (
                            <View style={[styles.landmarkBadge, isDarkMode && styles.landmarkBadgeDark]}>
                              <Text style={[styles.landmarkBadgeText, isDarkMode && styles.accentTextDark]}>LANDMARK</Text>
                            </View>
                          )}
                        </View>
                        <Text style={[styles.suggestionSub, isDarkMode && styles.mutedTextDark]} numberOfLines={1}>
                          {secondaryName || 'Washington, DC'}
                        </Text>
                      </View>
                      <ChevronRight size={18} color={isDarkMode ? '#747b85' : '#9aa0a6'} />
                    </TouchableOpacity>
                  );
                }}
              />
            </View>
          ) : (
            <ScrollView
              style={[styles.optionsScroll, isDarkMode && styles.expandedOverlayDark]}
              contentContainerStyle={styles.optionsContent}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
            >
              <View style={styles.quickActionRow}>
                <TouchableOpacity style={styles.quickChip} onPress={useCurrentLocation} activeOpacity={0.75}>
                  <LocateFixed size={16} color="#1967d2" />
                  <Text style={styles.quickChipText}>Current</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.quickChip} onPress={useDemoRoute} activeOpacity={0.75}>
                  <MapPin size={16} color="#1967d2" />
                  <Text style={styles.quickChipText}>Demo route</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.quickChip} onPress={swapRouteEndpoints} activeOpacity={0.75}>
                  <Repeat2 size={16} color="#1967d2" />
                  <Text style={styles.quickChipText}>Swap</Text>
                </TouchableOpacity>
              </View>

              <View style={[styles.optionSection, isDarkMode && styles.surfaceDark]}>
                <Text style={[styles.sectionTitle, isDarkMode && styles.textDark]}>Route profile</Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.profileRow}>
                  {ROUTE_PROFILES.map(profile => {
                    const selected = routePrefs.profile === profile.id;
                    const iconColor = selected ? '#1967d2' : '#5f6368';
                    return (
                      <TouchableOpacity
                        key={profile.id}
                        style={[styles.profileChip, isDarkMode && styles.controlSurfaceDark, selected && styles.profileChipActive, selected && isDarkMode && styles.controlActiveDark]}
                        onPress={() => selectRouteProfile(profile.id)}
                        activeOpacity={0.75}
                      >
                        <View style={[styles.profileIcon, selected && styles.profileIconActive]}>
                          {renderProfileIcon(profile.id, iconColor)}
                        </View>
                        <Text style={[styles.profileLabel, isDarkMode && styles.textDark, selected && styles.profileLabelActive, selected && isDarkMode && styles.accentTextDark]}>{profile.label}</Text>
                        <Text style={[styles.profileSub, isDarkMode && styles.mutedTextDark]}>{profile.sublabel}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </ScrollView>
              </View>

              <View style={[styles.optionSection, isDarkMode && styles.surfaceDark]}>
                <View style={styles.sectionHeaderRow}>
                  <Text style={[styles.sectionTitle, isDarkMode && styles.textDark]}>Leave</Text>
                  <Clock size={16} color={themeMuted} />
                </View>
                <View style={styles.compactChipRow}>
                  {DEPARTURE_OPTIONS.map(option => {
                    const selected = routePrefs.departurePreset === option.id;
                    return (
                      <TouchableOpacity
                        key={option.id}
                        style={[styles.compactChip, isDarkMode && styles.controlSurfaceDark, selected && styles.compactChipActive, selected && isDarkMode && styles.controlActiveDark]}
                        onPress={() => updateRoutePref('departurePreset', option.id)}
                        activeOpacity={0.75}
                      >
                        <Text style={[styles.compactChipText, isDarkMode && styles.mutedTextDark, selected && styles.compactChipTextActive, selected && isDarkMode && styles.accentTextDark]}>{option.label}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>

              <View style={[styles.optionSection, isDarkMode && styles.surfaceDark]}>
                <Text style={[styles.sectionTitle, isDarkMode && styles.textDark]}>Comfort priorities</Text>
                <View style={styles.toggleGrid}>
                  <TouchableOpacity
                    style={[styles.toggleTile, isDarkMode && styles.controlSurfaceDark, routePrefs.cooling && styles.toggleTileActive, routePrefs.cooling && isDarkMode && styles.controlActiveDark]}
                    onPress={() => toggleRoutePref('cooling')}
                    activeOpacity={0.75}
                  >
                    <Sun size={18} color={routePrefs.cooling ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, isDarkMode && styles.textDark, routePrefs.cooling && styles.toggleTitleActive, routePrefs.cooling && isDarkMode && styles.accentTextDark]}>Max shade</Text>
                      <Text style={[styles.toggleSub, isDarkMode && styles.mutedTextDark]}>UTCI</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, isDarkMode && styles.controlSurfaceDark, routePrefs.quiet && styles.toggleTileActive, routePrefs.quiet && isDarkMode && styles.controlActiveDark]}
                    onPress={() => toggleRoutePref('quiet')}
                    activeOpacity={0.75}
                  >
                    <Volume2 size={18} color={routePrefs.quiet ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, isDarkMode && styles.textDark, routePrefs.quiet && styles.toggleTitleActive, routePrefs.quiet && isDarkMode && styles.accentTextDark]}>Quiet streets</Text>
                      <Text style={[styles.toggleSub, isDarkMode && styles.mutedTextDark]}>Traffic</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, isDarkMode && styles.controlSurfaceDark, routePrefs.scenic && styles.toggleTileActive, routePrefs.scenic && isDarkMode && styles.controlActiveDark]}
                    onPress={() => toggleRoutePref('scenic')}
                    activeOpacity={0.75}
                  >
                    <Leaf size={18} color={routePrefs.scenic ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, isDarkMode && styles.textDark, routePrefs.scenic && styles.toggleTitleActive, routePrefs.scenic && isDarkMode && styles.accentTextDark]}>Green blocks</Text>
                      <Text style={[styles.toggleSub, isDarkMode && styles.mutedTextDark]}>Canopy</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, isDarkMode && styles.controlSurfaceDark, routePrefs.avoidHills && styles.toggleTileActive, routePrefs.avoidHills && isDarkMode && styles.controlActiveDark]}
                    onPress={() => toggleRoutePref('avoidHills')}
                    activeOpacity={0.75}
                  >
                    <Mountain size={18} color={routePrefs.avoidHills ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, isDarkMode && styles.textDark, routePrefs.avoidHills && styles.toggleTitleActive, routePrefs.avoidHills && isDarkMode && styles.accentTextDark]}>Flatter</Text>
                      <Text style={[styles.toggleSub, isDarkMode && styles.mutedTextDark]}>Slope</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, isDarkMode && styles.controlSurfaceDark, routePrefs.preferFast && styles.toggleTileActive, routePrefs.preferFast && isDarkMode && styles.controlActiveDark]}
                    onPress={() => toggleRoutePref('preferFast')}
                    activeOpacity={0.75}
                  >
                    <Navigation size={18} color={routePrefs.preferFast ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, isDarkMode && styles.textDark, routePrefs.preferFast && styles.toggleTitleActive, routePrefs.preferFast && isDarkMode && styles.accentTextDark]}>Keep short</Text>
                      <Text style={[styles.toggleSub, isDarkMode && styles.mutedTextDark]}>Time</Text>
                    </View>
                  </TouchableOpacity>
                </View>
              </View>

              <View style={[styles.optionSection, isDarkMode && styles.surfaceDark]}>
                <Text style={[styles.sectionTitle, isDarkMode && styles.textDark]}>Detour budget</Text>
                <View style={styles.budgetRow}>
                  {DETOUR_OPTIONS.map(option => {
                    const selected = routePrefs.detourBudget === option.id;
                    return (
                      <TouchableOpacity
                        key={option.id}
                        style={[styles.budgetChip, isDarkMode && styles.controlSurfaceDark, selected && styles.budgetChipActive, selected && isDarkMode && styles.controlActiveDark]}
                        onPress={() => updateRoutePref('detourBudget', option.id)}
                        activeOpacity={0.75}
                      >
                        <Text style={[styles.budgetLabel, isDarkMode && styles.textDark, selected && styles.budgetLabelActive, selected && isDarkMode && styles.accentTextDark]}>{option.label}</Text>
                        <Text style={[styles.budgetSub, isDarkMode && styles.mutedTextDark]}>{option.sublabel}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>

              <View style={[styles.optionSection, isDarkMode && styles.surfaceDark]}>
                <Text style={[styles.sectionTitle, isDarkMode && styles.textDark]}>Stops and alternatives</Text>
                <View style={styles.toggleGrid}>
                  <TouchableOpacity
                    style={[styles.toggleTile, isDarkMode && styles.controlSurfaceDark, routePrefs.showBenches && styles.toggleTileActive, routePrefs.showBenches && isDarkMode && styles.controlActiveDark]}
                    onPress={() => toggleRoutePref('showBenches')}
                    activeOpacity={0.75}
                  >
                    <Armchair size={18} color={routePrefs.showBenches ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, isDarkMode && styles.textDark, routePrefs.showBenches && styles.toggleTitleActive, routePrefs.showBenches && isDarkMode && styles.accentTextDark]}>Benches</Text>
                      <Text style={[styles.toggleSub, isDarkMode && styles.mutedTextDark]}>On map</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, isDarkMode && styles.controlSurfaceDark, routePrefs.showWater && styles.toggleTileActive, routePrefs.showWater && isDarkMode && styles.controlActiveDark]}
                    onPress={() => toggleRoutePref('showWater')}
                    activeOpacity={0.75}
                  >
                    <Droplets size={18} color={routePrefs.showWater ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, isDarkMode && styles.textDark, routePrefs.showWater && styles.toggleTitleActive, routePrefs.showWater && isDarkMode && styles.accentTextDark]}>Water</Text>
                      <Text style={[styles.toggleSub, isDarkMode && styles.mutedTextDark]}>On map</Text>
                    </View>
                  </TouchableOpacity>
                </View>
                <View style={styles.alternativesGroup}>
                  <Text style={[styles.subsectionLabel, isDarkMode && styles.mutedTextDark]}>Route alternatives</Text>
                  <View style={styles.compactChipRow}>
                    {CANDIDATE_OPTIONS.map(count => {
                      const selected = routePrefs.maxCandidates === count;
                      return (
                        <TouchableOpacity
                          key={count}
                          style={[styles.compactChip, isDarkMode && styles.controlSurfaceDark, selected && styles.compactChipActive, selected && isDarkMode && styles.controlActiveDark]}
                          onPress={() => updateRoutePref('maxCandidates', count)}
                          activeOpacity={0.75}
                        >
                          <Text style={[styles.compactChipText, isDarkMode && styles.mutedTextDark, selected && styles.compactChipTextActive, selected && isDarkMode && styles.accentTextDark]}>{count} route{count > 1 ? 's' : ''}</Text>
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                </View>
              </View>

              <View style={styles.findBtnWrap}>
              <TouchableOpacity style={styles.findBtn} onPress={() => fetchDualRoute()}>
                <Navigation size={18} color="#fff" style={{ marginRight: 8 }} />
                <Text style={styles.findBtnText}>Find route</Text>
              </TouchableOpacity>
              </View>
            </ScrollView>
          )}
        </View>
      )}

      {!isExpanded && !comparison && !isNavigating && (
        <BottomSheet
          ref={homeSheetRef}
          index={SHEET_COLLAPSED_INDEX}
          snapPoints={sheetSnapPoints}
          enablePanDownToClose={false}
          backgroundStyle={[styles.sheetBg, isDarkMode && styles.sheetBgDark]}
          handleIndicatorStyle={[styles.sheetHandle, isDarkMode && styles.sheetHandleDark]}
        >
          <BottomSheetScrollView
            contentContainerStyle={[styles.supportHomePanelContent, { paddingBottom: insets.bottom + 24 }]}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            <View style={styles.supportPanelHeader}>
              <View style={styles.supportHeaderCopy}>
                <Text style={[styles.supportEyebrow, isDarkMode && styles.accentTextDark]}>CLEARHELP DC · FOR PARENTS & CAREGIVERS</Text>
                <Text style={[styles.supportTitle, isDarkMode && styles.textDark]}>Understand a benefits notice. Know what to do next.</Text>
                <Text style={[styles.supportAudienceText, isDarkMode && styles.mutedTextDark]}>
                  Built for a caregiver under financial stress facing a school-meal, food-benefit, or housing letter.
                </Text>
              </View>
              <View style={styles.aiBadge}>
                <Sparkles size={14} color="#1967d2" />
                <Text style={styles.aiBadgeText}>On-device AI</Text>
              </View>
            </View>

            <View style={[styles.noticeInputWrap, isDarkMode && styles.controlSurfaceDark]}>
              <Search size={17} color={themeMuted} />
              <TextInput
                style={[styles.noticeInput, isDarkMode && styles.textDark]}
                placeholder="Paste a food-benefit, school-meal, or housing notice"
                placeholderTextColor={isDarkMode ? '#858c96' : '#8a9099'}
                value={supportNoticeText}
                onChangeText={setSupportNoticeText}
                multiline
              />
              <TouchableOpacity style={styles.explainBtn} onPress={buildSupportPlan} activeOpacity={0.8} accessibilityLabel="Explain this notice">
                <Sparkles size={15} color="#fff" />
              </TouchableOpacity>
            </View>

            {!supportNoticeText.trim() && (
              <TouchableOpacity
                style={styles.sampleNoticeAction}
                onPress={() => setSupportNoticeText(SAMPLE_NOTICE)}
                activeOpacity={0.75}
              >
                <Text style={styles.sampleNoticeText}>Try a sample school-meal notice</Text>
              </TouchableOpacity>
            )}

            <View style={[styles.responsibleAiStrip, isDarkMode && styles.responsibleAiStripDark]}>
              <ShieldCheck size={16} color="#137333" />
              <Text style={[styles.responsibleAiText, isDarkMode && styles.textDark]}>
                <Text style={styles.responsibleAiStrong}>Private. Human review required. </Text>
                Text stays on this device. Remove names and case numbers. AI can misclassify or surface outdated help, so confidence labels and human verification are required.
              </Text>
            </View>

            <View style={styles.categoryRow}>
              {SUPPORT_CATEGORIES.map(category => {
                const selected = selectedSupportCategory === category.id;
                return (
                  <TouchableOpacity
                    key={category.id}
                    style={[styles.categoryChip, isDarkMode && styles.controlSurfaceDark, selected && styles.categoryChipActive, selected && isDarkMode && styles.controlActiveDark]}
                    onPress={() => selectSupportCategory(category.id)}
                    activeOpacity={0.75}
                  >
                    <Text style={[styles.categoryText, isDarkMode && styles.mutedTextDark, selected && styles.categoryTextActive, selected && isDarkMode && styles.accentTextDark]}>{category.label}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>

            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.homeCardsRow}>
              {supportPlan && (
                <View style={[styles.homeInfoCard, styles.planCard, isDarkMode && styles.planCardDark]}>
                  <View style={styles.planHeaderRow}>
                    <View style={styles.urgencyPill}>
                      <Clock size={12} color="#a14200" />
                      <Text style={styles.urgencyText}>{supportPlan.urgency}</Text>
                    </View>
                    <Text style={styles.confidenceText}>
                      {supportPlan.confidence} confidence
                    </Text>
                  </View>
                  <Text style={[styles.planTitle, isDarkMode && styles.textDark]}>{supportPlan.title}</Text>
                  <Text style={[styles.planBody, isDarkMode && styles.textDark]}>{supportPlan.plainLanguage}</Text>
                  <Text style={[styles.whyResultText, isDarkMode && styles.mutedTextDark]}>{supportPlan.whyThisResult}</Text>
                  <Text style={[styles.planSectionLabel, isDarkMode && styles.accentTextDark]}>WHAT THE AI FOUND</Text>
                  <View style={styles.detailPreview}>
                    {supportPlan.keyDetails.slice(0, 4).map(item => (
                      <View key={item} style={styles.detailRow}>
                        <View style={styles.detailDot} />
                        <Text style={[styles.detailText, isDarkMode && styles.textDark]}>{item}</Text>
                      </View>
                    ))}
                  </View>
                  <Text style={[styles.planSectionLabel, isDarkMode && styles.accentTextDark]}>YOUR CHECKLIST</Text>
                  <View style={styles.checklistPreview}>
                    {supportPlan.checklist.slice(0, 3).map(item => (
                      <View key={item} style={styles.checkRow}>
                        <ClipboardCheck size={13} color="#137333" />
                        <Text style={[styles.checkText, isDarkMode && styles.textDark]}>{item}</Text>
                      </View>
                    ))}
                  </View>
                  <View style={styles.nextStepRow}>
                    <Text style={styles.nextStepLabel}>NEXT</Text>
                    <Text style={[styles.nextStepText, isDarkMode && styles.textDark]}>{supportPlan.nextSteps[0]}</Text>
                  </View>
                  <View style={styles.guardrailRow}>
                    <ShieldCheck size={13} color="#5f6368" />
                    <Text style={[styles.guardrailText, isDarkMode && styles.mutedTextDark]}>{supportPlan.humanDecision}</Text>
                  </View>
                </View>
              )}

              {visibleSupportResources.map(resource => {
                const selected = selectedResource?.id === resource.id;
                return (
                  <TouchableOpacity
                    key={resource.id}
                    style={[styles.homeInfoCard, isDarkMode && styles.homeInfoCardDark, selected && styles.resourceCardSelected, selected && isDarkMode && styles.resourceCardSelectedDark]}
                    onPress={() => focusSupportResource(resource)}
                    activeOpacity={0.85}
                  >
                    <View style={styles.resourceTopRow}>
                      <View style={[styles.resourceIconWrap, selected && styles.resourceIconWrapSelected]}>
                        {renderSupportIcon(resource.category, selected ? '#fff' : '#1967d2', 18)}
                      </View>
                      <Text style={[styles.resourceDistance, isDarkMode && styles.mutedTextDark]}>{resource.distanceLabel}</Text>
                    </View>
                    <Text style={[styles.resourceName, isDarkMode && styles.textDark]} numberOfLines={1}>{resource.name}</Text>
                    <Text style={styles.resourceStatus}>{resource.status}</Text>
                    <Text style={[styles.resourceSummary, isDarkMode && styles.mutedTextDark]} numberOfLines={2}>{resource.summary}</Text>
                    <Text style={[styles.resourceConfidence, isDarkMode && styles.mutedTextDark]}>Synthetic demo record · verify before acting</Text>
                    <View style={styles.resourceActions}>
                      <TouchableOpacity style={styles.resourceActionBtn} onPress={() => contactSupportResource(resource)} activeOpacity={0.75}>
                        <Phone size={13} color="#1967d2" />
                        <Text style={styles.resourceActionText}>Contact</Text>
                      </TouchableOpacity>
                      <TouchableOpacity style={[styles.resourceActionBtn, styles.primaryResourceAction]} onPress={() => routeToSupportResource(resource)} activeOpacity={0.75}>
                        <Text style={styles.primaryResourceActionText}>Directions</Text>
                      </TouchableOpacity>
                    </View>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </BottomSheetScrollView>
        </BottomSheet>
      )}

      {/* ---- Layer Toggle Button ---- */}
      {!isExpanded && !isNavigating && (
        <TouchableOpacity
          style={[styles.layerToggle, { bottom: floatingControlBottom }]}
          onPress={() => setMapType(mapType === 'standard' ? 'satellite' : 'standard')}
          activeOpacity={0.85}
        >
          <Layers size={16} color="#fff" />
          <Text style={styles.layerToggleText}>
            {mapType === 'standard' ? 'Satellite' : 'Map'}
          </Text>
        </TouchableOpacity>
      )}

      {/* ---- Navigation Detour Buttons / Resume Journey ---- */}
      {isNavigating && (originalDestination || routePrefs.showBenches || routePrefs.showWater) && (
        <View style={[styles.detourContainer, { top: insets.top + 20 }]}>
          {originalDestination ? (
            <TouchableOpacity style={[styles.detourBtn, { backgroundColor: '#e8f0fe', borderColor: '#4285f4', borderWidth: 2 }]} onPress={handleResumeJourney} activeOpacity={0.8}>
              <Text style={[styles.detourText, { color: '#1967d2' }]}>Resume Journey</Text>
            </TouchableOpacity>
          ) : (
            <>
              {routePrefs.showBenches && (
                <TouchableOpacity style={styles.detourBtn} onPress={() => handleDetour('bench')} activeOpacity={0.8}>
                  <Armchair size={16} color="#202124" />
                  <Text style={styles.detourText}>Bench stop</Text>
                </TouchableOpacity>
              )}
              {routePrefs.showWater && (
                <TouchableOpacity style={styles.detourBtn} onPress={() => handleDetour('water')} activeOpacity={0.8}>
                  <Droplets size={16} color="#202124" />
                  <Text style={styles.detourText}>Water stop</Text>
                </TouchableOpacity>
              )}
            </>
          )}
        </View>
      )}

      {/* ---- Re-center Button ---- */}
      {isNavigating && !followMode && (
        <TouchableOpacity
          style={[styles.recenterBtn, { bottom: 100 + insets.bottom }]}
          onPress={toggleFollowMode}
          activeOpacity={0.85}
        >
          <Navigation size={18} color="#202124" />
          <Text style={styles.recenterText}>Re-center</Text>
        </TouchableOpacity>
      )}

      {isNavigating && navigationPhase !== 'preview' && (
        <TouchableOpacity
          style={[
            styles.navigationStatusBanner,
            (isOffRoute || isGpsWeak) && styles.navigationStatusBannerWarning,
            { top: insets.top + (originalDestination || routePrefs.showBenches || routePrefs.showWater ? 78 : 16) },
          ]}
          onPress={() => {
            if (isOffRoute && navigationPositionRef.current && destinationCoords && !loading) {
              void fetchDualRoute(navigationPositionRef.current, destinationCoords);
            }
          }}
          disabled={!isOffRoute || loading}
          activeOpacity={isOffRoute ? 0.8 : 1}
        >
          {navigationPhase === 'starting'
            ? <ActivityIndicator size="small" color="#fff" />
            : <Navigation size={16} color="#fff" />}
          <Text style={styles.navigationStatusText}>{navigationStatusText}</Text>
          {isOffRoute && <Text style={styles.navigationRerouteText}>REROUTE</Text>}
        </TouchableOpacity>
      )}

      {/* ---- Navigation Mode Bottom Bar ---- */}
      {isNavigating && (
        <View style={[styles.navBottomBar, { paddingBottom: insets.bottom + 10 }]}>
          <View style={styles.navBarInfo}>
            <Text style={styles.navBarTime}>
              {isArriving ? 'Arrived' : comparison ? `${Math.max(1, Math.round(remainingDurationSeconds / 60))} min` : '--'}
            </Text>
            <Text style={styles.navBarDist}>
              {isArriving ? 'Destination reached' : comparison ? `${(remainingDistanceM / 1609.34).toFixed(2)} mi remaining` : ''}
              {originalDestination ? ' (to detour)' : ''}
            </Text>
          </View>
          <TouchableOpacity
            style={styles.navToggleBtn}
            onPress={toggleFollowMode}
            activeOpacity={0.8}
            accessibilityLabel={followMode ? 'Unlock map' : 'Follow my position'}
          >
            {followMode ? (
              <MapIcon size={20} color="#fff" />
            ) : (
              <LocateFixed size={20} color="#fff" />
            )}
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.navExitBtn}
            onPress={exitNavigation}
            activeOpacity={0.8}
          >
            <Text style={styles.navExitText}>Exit</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* ---- Loading ---- */}
      {loading && (
        <View style={styles.loadingOverlay}>
          <View style={[styles.loadingBox, isDarkMode && styles.surfaceDark]}>
            <ActivityIndicator size="large" color="#4285f4" />
            <Text style={[styles.loadingText, isDarkMode && styles.textDark]}>
              {isNavigating ? 'Updating route…' : 'Calculating routes…'}
            </Text>
          </View>
        </View>
      )}

      {/* ---- Bottom Sheet ---- */}
      {comparison && (
        <BottomSheet
          ref={routeSheetRef}
          index={SHEET_COLLAPSED_INDEX}
          snapPoints={sheetSnapPoints}
          enablePanDownToClose={false}
          backgroundStyle={[styles.sheetBg, isDarkMode && styles.sheetBgDark]}
          handleIndicatorStyle={[styles.sheetHandle, isDarkMode && styles.sheetHandleDark]}
        >
          <BottomSheetScrollView contentContainerStyle={styles.sheetContent}>
            <View style={styles.resultHeader}>
              <View>
                <View style={styles.recommendedPill}>
                  <Sparkles size={13} color="#0b57d0" />
                  <Text style={styles.recommendedText}>RECOMMENDED</Text>
                </View>
                <Text style={[styles.resultTitle, isDarkMode && styles.textDark]}>{Math.round(comparison.cool_duration_seconds / 60)} min</Text>
                <Text style={[styles.resultSubtitle, isDarkMode && styles.mutedTextDark]}>
                  {(comparison.cool_total_meters / 1609.34).toFixed(2)} mi · {ROUTE_PROFILES.find(item => item.id === routePrefs.profile)?.label} route
                </Text>
              </View>
              <TouchableOpacity onPress={handleCloseRoutePanel} style={[styles.closeButton, isDarkMode && styles.headerIconBtnDark]}>
                <X size={22} color={themeText} />
              </TouchableOpacity>
            </View>

            <View style={[styles.insightStrip, isDarkMode && styles.controlSurfaceDark]}>
              <View style={styles.insightItem}>
                <Sun size={17} color="#b06000" />
                <Text style={[styles.insightValue, isDarkMode && styles.textDark]}>{Math.max(0, comparison.standard_mean_utci - comparison.cool_mean_utci).toFixed(1)}°</Text>
                <Text style={[styles.insightLabel, isDarkMode && styles.mutedTextDark]}>cooler</Text>
              </View>
              <View style={styles.insightDivider} />
              <View style={styles.insightItem}>
                <Leaf size={17} color="#137333" />
                <Text style={[styles.insightValue, isDarkMode && styles.textDark]}>{Math.round(comparison.cool_shade_score)}%</Text>
                <Text style={[styles.insightLabel, isDarkMode && styles.mutedTextDark]}>shade</Text>
              </View>
              <View style={styles.insightDivider} />
              <View style={styles.insightItem}>
                <Route size={17} color="#0b57d0" />
                <Text style={[styles.insightValue, isDarkMode && styles.textDark]}>+{Math.max(0, Math.round(comparison.extra_distance_meters))}m</Text>
                <Text style={[styles.insightLabel, isDarkMode && styles.mutedTextDark]}>detour</Text>
              </View>
            </View>

            <View style={[styles.climateSourceCard, isDarkMode && styles.controlSurfaceDark]}>
              <View style={styles.climateSourceIcon}><Clock size={16} color="#0b57d0" /></View>
              <View style={styles.climateSourceCopy}>
                <Text style={[styles.climateSourceLabel, isDarkMode && styles.mutedTextDark]}>Climate model snapshot</Text>
                <Text style={[styles.climateSourceValue, isDarkMode && styles.textDark]}>
                  {comparison.utci_time ? new Date(comparison.utci_time).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Synthetic development data'}
                  {comparison.uses_nearest_time ? ' · nearest available' : ''}
                </Text>
              </View>
              <ShieldCheck size={17} color="#137333" />
            </View>

            <View style={styles.metricGrid}>
              <View style={[styles.miniMetric, isDarkMode && styles.controlSurfaceDark]}>
                <Text style={[styles.miniMetricLabel, isDarkMode && styles.mutedTextDark]}>Scenic</Text>
                <Text style={[styles.miniMetricValue, isDarkMode && styles.textDark]}>{Math.round(comparison.scenic_score * 100)}<Text style={styles.metricUnit}>/100</Text></Text>
              </View>
              <View style={[styles.miniMetric, isDarkMode && styles.controlSurfaceDark]}>
                <Text style={[styles.miniMetricLabel, isDarkMode && styles.mutedTextDark]}>Quiet</Text>
                <Text style={[styles.miniMetricValue, isDarkMode && styles.textDark]}>{Math.round(Math.max(0, 1 - comparison.noise_score) * 100)}<Text style={styles.metricUnit}>/100</Text></Text>
              </View>
              <View style={[styles.miniMetric, isDarkMode && styles.controlSurfaceDark]}>
                <Text style={[styles.miniMetricLabel, isDarkMode && styles.mutedTextDark]}>Slope</Text>
                <Text style={[styles.miniMetricValue, isDarkMode && styles.textDark]}>{(comparison.slope_penalty * 100).toFixed(1)}%</Text>
              </View>
              <View style={[styles.miniMetric, isDarkMode && styles.controlSurfaceDark]}>
                <Text style={[styles.miniMetricLabel, isDarkMode && styles.mutedTextDark]}>Heat dose</Text>
                <Text style={[styles.miniMetricValue, isDarkMode && styles.textDark]}>{comparison.cool_heat_dose.toFixed(1)}</Text>
              </View>
            </View>
            <Text style={[styles.candidateText, isDarkMode && styles.mutedTextDark]}>{comparison.route_candidate_count} viable route{comparison.route_candidate_count === 1 ? '' : 's'} evaluated · real DC street and LiDAR data</Text>
            {comparison.warnings.length > 0 && (
              <View style={styles.warningCard}>
                {comparison.warnings.map((warning, index) => (
                  <Text key={`${warning}-${index}`} style={styles.warningText}>{warning}</Text>
                ))}
              </View>
            )}
            {!isNavigating && (
              <TouchableOpacity
                style={styles.navBtn}
                onPress={startNavigation}
                activeOpacity={0.82}
                accessibilityLabel="Start navigation"
                accessibilityRole="button"
              >
                <Navigation size={18} color="#fff" style={{ marginRight: 8 }} />
                <Text style={styles.navBtnText}>Start navigation</Text>
              </TouchableOpacity>
            )}
            <View style={{ height: 30 }} />
          </BottomSheetScrollView>
        </BottomSheet>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  map: { ...StyleSheet.absoluteFillObject },

  // --- Collapsed bar ---
  collapsedBar: {
    position: 'absolute', left: 16, right: 16, zIndex: 20,
    backgroundColor: '#fff', borderRadius: 28, height: 52,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.15, shadowRadius: 8, elevation: 5,
  },
  collapsedInner: { flex: 1, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8 },
  appIcon: {
    width: 36, height: 36, borderRadius: 18, backgroundColor: '#34a853',
    justifyContent: 'center', alignItems: 'center', marginRight: 12,
  },
  collapsedText: { flex: 1, fontSize: 16, color: '#5f6368' },
  collapsedBarDark: { backgroundColor: '#181b20', borderWidth: 1, borderColor: '#30343b' },
  themeToggle: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: '#f1f3f4' },
  themeToggleDark: { backgroundColor: '#2b3037' },
  textDark: { color: '#f1f3f4' },
  mutedTextDark: { color: '#aeb4bd' },
  accentTextDark: { color: '#8ab4f8' },
  surfaceDark: { backgroundColor: '#181b20', borderColor: '#30343b' },
  profileCircle: {
    width: 32, height: 32, borderRadius: 16, backgroundColor: '#8e44ad',
    justifyContent: 'center', alignItems: 'center',
  },
  profileInitial: { color: '#fff', fontWeight: '700', fontSize: 14 },

  // --- Home Support Panel ---
  supportHomePanelContent: {
    paddingHorizontal: 16,
    paddingTop: 2,
  },
  supportPanelHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 12,
    marginBottom: 12,
  },
  supportHeaderCopy: { flex: 1 },
  supportEyebrow: { fontSize: 12, fontWeight: '800', color: '#1967d2', marginBottom: 2 },
  supportTitle: { fontSize: 19, fontWeight: '800', color: '#202124', maxWidth: 285, lineHeight: 24 },
  supportAudienceText: { fontSize: 11, lineHeight: 15, color: '#5f6368', marginTop: 5, maxWidth: 295 },
  aiBadge: {
    height: 30,
    borderRadius: 15,
    paddingHorizontal: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: '#e8f0fe',
  },
  aiBadgeText: { fontSize: 12, fontWeight: '800', color: '#1967d2' },
  noticeInputWrap: {
    minHeight: 50,
    borderRadius: 16,
    backgroundColor: '#f1f3f4',
    flexDirection: 'row',
    alignItems: 'center',
    paddingLeft: 13,
    paddingRight: 7,
    marginBottom: 12,
  },
  noticeInput: {
    flex: 1,
    minHeight: 44,
    maxHeight: 72,
    fontSize: 14,
    color: '#202124',
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  explainBtn: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1967d2',
  },
  sampleNoticeAction: { alignSelf: 'flex-start', marginTop: -4, marginBottom: 10, paddingVertical: 4 },
  sampleNoticeText: { color: '#1967d2', fontSize: 12, fontWeight: '800' },
  responsibleAiStrip: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 8, padding: 11, marginBottom: 12,
    backgroundColor: '#edf7ed', borderRadius: 12, borderWidth: 1, borderColor: '#cce8d0',
  },
  responsibleAiStripDark: { backgroundColor: '#183528', borderColor: '#29553e' },
  responsibleAiText: { flex: 1, fontSize: 11, lineHeight: 16, color: '#3c4043' },
  responsibleAiStrong: { fontWeight: '900', color: '#137333' },
  categoryRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 12 },
  categoryChip: {
    height: 34,
    borderRadius: 17,
    paddingHorizontal: 13,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f8fafd',
    borderWidth: 1,
    borderColor: '#e6e8eb',
  },
  categoryChipActive: { backgroundColor: '#e8f0fe', borderColor: '#4285f4' },
  categoryText: { fontSize: 13, fontWeight: '700', color: '#5f6368' },
  categoryTextActive: { color: '#1967d2' },
  homeCardsRow: { gap: 12, paddingRight: 4 },
  homeInfoCard: {
    width: 258,
    minHeight: 178,
    borderRadius: 16,
    padding: 14,
    backgroundColor: '#f8fafd',
    borderWidth: 1,
    borderColor: '#eceff3',
  },
  homeInfoCardDark: { backgroundColor: '#22262c', borderColor: '#343a43' },
  planCard: { width: 310, minHeight: 360, backgroundColor: '#fffaf2', borderColor: '#fad8a8' },
  planCardDark: { backgroundColor: '#2d261b', borderColor: '#705126' },
  planHeaderRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  urgencyPill: {
    height: 26,
    borderRadius: 13,
    paddingHorizontal: 9,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: '#fdebd3',
  },
  urgencyText: { fontSize: 12, fontWeight: '800', color: '#a14200' },
  confidenceText: { fontSize: 12, fontWeight: '800', color: '#5f6368' },
  planTitle: { fontSize: 16, fontWeight: '800', color: '#202124', marginBottom: 5 },
  planBody: { fontSize: 13, color: '#3c4043', lineHeight: 18, marginBottom: 8 },
  whyResultText: { fontSize: 11, lineHeight: 15, color: '#70757a', fontStyle: 'italic', marginBottom: 8 },
  planSectionLabel: { fontSize: 10, fontWeight: '900', color: '#1967d2', letterSpacing: 0.65, marginBottom: 6 },
  detailPreview: { gap: 5, marginBottom: 10 },
  detailRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 7 },
  detailDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#1967d2', marginTop: 5 },
  detailText: { flex: 1, fontSize: 12, lineHeight: 16, color: '#3c4043' },
  checklistPreview: { gap: 5, marginBottom: 9 },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  checkText: { flex: 1, fontSize: 12, fontWeight: '700', color: '#3c4043' },
  nextStepRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, backgroundColor: '#e8f0fe', borderRadius: 10, padding: 9, marginBottom: 9 },
  nextStepLabel: { fontSize: 10, fontWeight: '900', color: '#1967d2', letterSpacing: 0.6, marginTop: 1 },
  nextStepText: { flex: 1, fontSize: 12, lineHeight: 16, fontWeight: '800', color: '#202124' },
  guardrailRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6, paddingTop: 8, borderTopWidth: 1, borderTopColor: '#f2ddc4' },
  guardrailText: { flex: 1, fontSize: 11, lineHeight: 15, color: '#5f6368', fontWeight: '600' },
  resourceCardSelected: { backgroundColor: '#e8f0fe', borderColor: '#4285f4' },
  resourceCardSelectedDark: { backgroundColor: '#1e3557', borderColor: '#8ab4f8' },
  resourceTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  resourceIconWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#e6e8eb',
  },
  resourceIconWrapSelected: { backgroundColor: '#1967d2', borderColor: '#1967d2' },
  resourceDistance: { fontSize: 12, fontWeight: '800', color: '#5f6368' },
  resourceName: { fontSize: 16, fontWeight: '800', color: '#202124', marginBottom: 3 },
  resourceStatus: { fontSize: 12, fontWeight: '800', color: '#137333', marginBottom: 7 },
  resourceSummary: { fontSize: 12, lineHeight: 17, color: '#5f6368', marginBottom: 10 },
  resourceConfidence: { fontSize: 11, fontWeight: '700', color: '#70757a', marginBottom: 10 },
  resourceActions: { flexDirection: 'row', gap: 8, marginTop: 'auto' },
  resourceActionBtn: {
    height: 34,
    borderRadius: 17,
    paddingHorizontal: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 5,
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#d7e3fc',
  },
  resourceActionText: { fontSize: 12, fontWeight: '800', color: '#1967d2' },
  primaryResourceAction: { backgroundColor: '#1967d2', borderColor: '#1967d2' },
  primaryResourceActionText: { fontSize: 12, fontWeight: '800', color: '#fff' },

  // --- Expanded overlay (covers the map) ---
  expandedOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#f8f9fa',
    zIndex: 30,
    paddingHorizontal: 16,
  },
  expandedOverlayDark: { backgroundColor: '#101216' },
  expandedCard: {
    backgroundColor: '#fff', borderRadius: 18, paddingVertical: 12, paddingHorizontal: 12,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.1, shadowRadius: 8, elevation: 4,
  },
  directionsHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: 10 },
  directionsTitle: { flex: 1, fontSize: 18, fontWeight: '700', color: '#202124', marginLeft: 4 },
  headerIconBtn: {
    width: 38, height: 38, borderRadius: 19,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: '#f1f3f4',
  },
  headerIconBtnDark: { backgroundColor: '#2b3037' },
  expandedRow: { flexDirection: 'row', alignItems: 'flex-start' },
  backBtn: {
    width: 38, height: 38, borderRadius: 19,
    alignItems: 'center', justifyContent: 'center',
  },
  inputsCol: { flex: 1 },

  fieldRow: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: '#f8fafd', borderRadius: 10,
    paddingHorizontal: 14, height: 48,
    borderWidth: 1, borderColor: '#eef0f3',
  },
  fieldRowActive: {
    backgroundColor: '#e8f0fe', borderColor: '#4285f4',
  },
  fieldRowDark: { backgroundColor: '#22262c', borderColor: '#343a43' },
  fieldRowActiveDark: { backgroundColor: '#1e3557', borderColor: '#8ab4f8' },
  dotBlue: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#4285f4', marginRight: 12 },
  dotRed: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#ea4335', marginRight: 12 },
  fieldInput: { flex: 1, fontSize: 15, color: '#202124', height: '100%' },
  fieldDivider: { height: 6 },

  // --- Route Controls ---
  travelModeTabs: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#f1f3f4',
  },
  travelModeTab: {
    flex: 1,
    height: 42,
    borderRadius: 21,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#f1f3f4',
    borderWidth: 1,
    borderColor: '#f1f3f4',
  },
  travelModeTabActive: { backgroundColor: '#e8f0fe', borderColor: '#4285f4' },
  controlSurfaceDark: { backgroundColor: '#22262c', borderColor: '#343a43' },
  controlActiveDark: { backgroundColor: '#1e3557', borderColor: '#8ab4f8' },
  travelModeText: { fontSize: 14, fontWeight: '700', color: '#5f6368' },
  travelModeTextActive: { color: '#1967d2' },
  optionsScroll: { flex: 1 },
  optionsContent: { paddingVertical: 14, paddingBottom: 36 },
  quickActionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 14,
  },
  quickChip: {
    height: 38,
    borderRadius: 19,
    paddingHorizontal: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#dadce0',
  },
  quickChipText: { fontSize: 13, fontWeight: '700', color: '#1967d2' },
  optionSection: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#eceff3',
  },
  sectionHeaderRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sectionTitle: { fontSize: 15, fontWeight: '800', color: '#202124', marginBottom: 12 },
  alternativesGroup: { marginTop: 22, paddingTop: 16, borderTopWidth: 1, borderTopColor: '#eceff3' },
  subsectionLabel: { fontSize: 12, fontWeight: '800', color: '#70757a', marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.5 },
  profileRow: { gap: 10, paddingRight: 4 },
  profileChip: {
    width: 118,
    minHeight: 94,
    borderRadius: 14,
    padding: 12,
    backgroundColor: '#f8fafd',
    borderWidth: 1,
    borderColor: '#eef0f3',
  },
  profileChipActive: { backgroundColor: '#e8f0fe', borderColor: '#4285f4' },
  profileIcon: {
    width: 30, height: 30, borderRadius: 15,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: '#fff',
    borderWidth: 1, borderColor: '#e6e8eb',
    marginBottom: 8,
  },
  profileIconActive: { borderColor: '#c5d7ff' },
  profileLabel: { fontSize: 14, fontWeight: '800', color: '#202124' },
  profileLabelActive: { color: '#1967d2' },
  profileSub: { fontSize: 11, color: '#70757a', marginTop: 3, lineHeight: 15 },
  compactChipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  compactChip: {
    height: 36,
    borderRadius: 18,
    paddingHorizontal: 13,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f1f3f4',
    borderWidth: 1,
    borderColor: '#f1f3f4',
  },
  compactChipActive: { backgroundColor: '#e8f0fe', borderColor: '#4285f4' },
  compactChipText: { fontSize: 13, fontWeight: '700', color: '#5f6368' },
  compactChipTextActive: { color: '#1967d2' },
  toggleGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  toggleTile: {
    flexBasis: '47.5%',
    minHeight: 58,
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#f8fafd',
    borderWidth: 1,
    borderColor: '#eef0f3',
  },
  toggleTileActive: { backgroundColor: '#e8f0fe', borderColor: '#4285f4' },
  toggleTextCol: { flex: 1, minWidth: 0 },
  toggleTitle: { fontSize: 13, fontWeight: '800', color: '#202124' },
  toggleTitleActive: { color: '#1967d2' },
  toggleSub: { fontSize: 11, color: '#70757a', marginTop: 2 },
  budgetRow: { flexDirection: 'row', gap: 8 },
  budgetChip: {
    flex: 1,
    minHeight: 58,
    borderRadius: 14,
    paddingVertical: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f8fafd',
    borderWidth: 1,
    borderColor: '#eef0f3',
  },
  budgetChipActive: { backgroundColor: '#e8f0fe', borderColor: '#4285f4' },
  budgetLabel: { fontSize: 13, fontWeight: '800', color: '#202124' },
  budgetLabelActive: { color: '#1967d2' },
  budgetSub: { fontSize: 11, color: '#70757a', marginTop: 3 },

  // --- Autocomplete result panel ---
  suggestionsPanel: {
    flex: 1, marginTop: 12, marginBottom: 8, backgroundColor: '#fff', borderRadius: 20,
    borderWidth: 1, borderColor: '#e4e7eb', overflow: 'hidden',
    shadowColor: '#202124', shadowOffset: { width: 0, height: 5 }, shadowOpacity: 0.12, shadowRadius: 16, elevation: 6,
  },
  suggestionsPanelDark: { backgroundColor: '#181b20', borderColor: '#30343b', shadowColor: '#000' },
  suggestionsList: { flex: 1 },
  suggestionsContent: { paddingVertical: 5 },
  suggestionRow: {
    flexDirection: 'row', alignItems: 'center',
    minHeight: 72, paddingVertical: 10, paddingHorizontal: 14,
    backgroundColor: '#fff',
  },
  suggestionRowDark: { backgroundColor: '#181b20' },
  suggestionDivider: { height: 1, backgroundColor: '#eef0f3', marginLeft: 70, marginRight: 16 },
  suggestionDividerDark: { backgroundColor: '#2d3239' },
  suggestionIcon: {
    width: 42, height: 42, borderRadius: 14, backgroundColor: '#edf3ff',
    justifyContent: 'center', alignItems: 'center', marginRight: 13,
  },
  suggestionIconDark: { backgroundColor: '#1e3557' },
  suggestionTextCol: { flex: 1 },
  suggestionTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 7, paddingRight: 8 },
  suggestionMain: { flexShrink: 1, fontSize: 15, fontWeight: '800', color: '#202124' },
  suggestionSub: { fontSize: 12, color: '#70757a', marginTop: 4 },
  landmarkBadge: { borderRadius: 7, paddingHorizontal: 6, paddingVertical: 3, backgroundColor: '#edf3ff' },
  landmarkBadgeDark: { backgroundColor: '#1e3557' },
  landmarkBadgeText: { fontSize: 8, fontWeight: '900', color: '#1967d2', letterSpacing: 0.4 },

  // --- Find Route button ---
  findBtnWrap: { marginTop: 16 },
  findBtn: {
    flexDirection: 'row', backgroundColor: '#4285f4', paddingVertical: 14, borderRadius: 24,
    alignItems: 'center', justifyContent: 'center',
    shadowColor: '#4285f4', shadowOffset: { width: 0, height: 3 }, shadowOpacity: 0.3, shadowRadius: 6, elevation: 4,
  },
  findBtnText: { color: '#fff', fontSize: 16, fontWeight: '700' },

  // --- Layer Toggle ---
  layerToggle: {
    position: 'absolute', left: 16, width: 72, height: 72, borderRadius: 12,
    backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', alignItems: 'center',
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.3, shadowRadius: 6, elevation: 6,
    zIndex: 15, overflow: 'hidden',
  },
  layerToggleText: {
    color: '#fff', fontSize: 11, fontWeight: '700', marginTop: 4,
  },

  // --- POI Markers ---
  supportMarker: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: '#fff',
    borderWidth: 2,
    borderColor: '#1967d2',
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 5,
    elevation: 5,
  },
  supportMarkerSelected: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#1967d2',
    borderColor: '#fff',
  },
  benchMarker: {
    backgroundColor: 'white', padding: 3, borderRadius: 12,
    borderWidth: 1, borderColor: '#1a73e8',
  },
  waterMarker: {
    backgroundColor: 'white', padding: 3, borderRadius: 12,
    borderWidth: 1, borderColor: '#2196F3',
  },
  poiEmoji: { fontSize: 12 },

  // --- POI Status Pill ---
  poiStatusWrap: {
    position: 'absolute', left: 0, right: 0,
    alignItems: 'center', zIndex: 15,
  },
  poiPill: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.92)',
    paddingHorizontal: 14, paddingVertical: 7,
    borderRadius: 20,
    borderWidth: 1, borderColor: '#e0e0e0',
    shadowColor: '#000', shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.08, shadowRadius: 4, elevation: 3,
  },
  poiPillText: { fontSize: 12, color: '#555' },

  // --- Loading ---
  loadingOverlay: {
    ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.35)',
    justifyContent: 'center', alignItems: 'center', zIndex: 100,
  },
  loadingBox: {
    backgroundColor: 'white', padding: 28, borderRadius: 20, alignItems: 'center',
    shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 10, elevation: 8,
  },
  loadingText: { marginTop: 14, fontSize: 16, fontWeight: '600', color: '#202124' },

  // --- Bottom Sheet ---
  sheetBg: { borderRadius: 28, backgroundColor: '#fff' },
  sheetHandle: { backgroundColor: '#dadce0', width: 40 },
  sheetBgDark: { backgroundColor: '#181b20' },
  sheetHandleDark: { backgroundColor: '#59616c' },
  sheetContent: { padding: 24 },
  resultHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 18 },
  recommendedPill: { alignSelf: 'flex-start', flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: '#edf3ff', borderRadius: 10, paddingHorizontal: 8, paddingVertical: 5, marginBottom: 7 },
  recommendedText: { fontSize: 10, fontWeight: '900', color: '#0b57d0', letterSpacing: 0.8 },
  resultTitle: { fontSize: 32, lineHeight: 36, fontWeight: '900', color: '#1f1f1f' },
  resultSubtitle: { fontSize: 14, fontWeight: '600', color: '#5e6268', marginTop: 3 },
  closeButton: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#f1f3f4', alignItems: 'center', justifyContent: 'center' },
  insightStrip: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#f7f9fc', borderRadius: 18, paddingVertical: 14, paddingHorizontal: 8, marginBottom: 14 },
  insightItem: { flex: 1, alignItems: 'center', gap: 2 },
  insightDivider: { width: 1, height: 38, backgroundColor: '#dfe3e8' },
  insightValue: { fontSize: 16, fontWeight: '900', color: '#1f1f1f' },
  insightLabel: { fontSize: 10, fontWeight: '700', color: '#7a7f87', textTransform: 'uppercase', letterSpacing: 0.5 },
  climateSourceCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#fff', borderRadius: 16, borderWidth: 1, borderColor: '#dfe3e8', padding: 12, marginBottom: 14 },
  climateSourceIcon: { width: 34, height: 34, borderRadius: 12, backgroundColor: '#edf3ff', alignItems: 'center', justifyContent: 'center', marginRight: 10 },
  climateSourceCopy: { flex: 1 },
  climateSourceLabel: { fontSize: 11, fontWeight: '800', color: '#7a7f87', textTransform: 'uppercase', letterSpacing: 0.4 },
  climateSourceValue: { fontSize: 13, fontWeight: '700', color: '#30343b', marginTop: 2 },
  sheetTitle: { fontSize: 22, fontWeight: '800', marginBottom: 18, color: '#202124' },
  compRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 18 },
  statBlock: { flex: 1, padding: 14, borderRadius: 14, borderWidth: 2, marginHorizontal: 4 },
  statGray: { borderColor: '#dadce0', backgroundColor: '#fafafa' },
  statGreen: { borderColor: '#34a853', backgroundColor: '#e6f4ea' },
  statLabel: { fontSize: 13, fontWeight: '700', color: '#5f6368', marginBottom: 4 },
  statVal: { fontSize: 20, fontWeight: '800', color: '#202124' },
  statSub: { fontSize: 12, fontWeight: '600', color: '#70757a', marginTop: 4 },
  metricCard: { backgroundColor: '#f1f3f4', padding: 14, borderRadius: 14, alignItems: 'center', marginBottom: 14 },
  metricText: { fontSize: 15, color: '#202124', textAlign: 'center', lineHeight: 22 },
  hl: { fontSize: 17, fontWeight: '800', color: '#4285f4' },
  metricGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 10 },
  miniMetric: {
    flexBasis: '47.5%',
    backgroundColor: '#f8fafd',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#eceff3',
    paddingVertical: 12,
    paddingHorizontal: 10,
    alignItems: 'center',
  },
  miniMetricLabel: { fontSize: 11, fontWeight: '700', color: '#70757a', marginBottom: 4 },
  miniMetricValue: { fontSize: 16, fontWeight: '800', color: '#202124' },
  metricUnit: { fontSize: 10, fontWeight: '700', color: '#7a7f87' },
  candidateText: { fontSize: 12, fontWeight: '700', color: '#70757a', textAlign: 'center', marginBottom: 14 },
  warningCard: { backgroundColor: '#fff8e1', padding: 12, borderRadius: 12, borderWidth: 1, borderColor: '#fbbc04', marginBottom: 14 },
  warningText: { fontSize: 12, color: '#5f3b00', lineHeight: 17 },
  navBtn: {
    flexDirection: 'row', backgroundColor: '#0b57d0', padding: 16, borderRadius: 18,
    alignItems: 'center', justifyContent: 'center', marginTop: 8,
    shadowColor: '#0b57d0', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.25, shadowRadius: 10, elevation: 6,
  },
  navBtnText: { color: 'white', fontSize: 17, fontWeight: '700' },

  // --- Live Location Marker ---
  userDotWrap: { width: 32, height: 32, justifyContent: 'center', alignItems: 'center' },
  userDotHalo: { position: 'absolute', width: 28, height: 28, borderRadius: 14, backgroundColor: 'rgba(66, 133, 244, 0.25)' },
  userDotLine: { position: 'absolute', width: 14, height: 14, borderRadius: 7, backgroundColor: '#fff', shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.3, shadowRadius: 4 },
  userDotCenter: { position: 'absolute', width: 10, height: 10, borderRadius: 5, backgroundColor: '#4285f4' },

  // --- Navigation Mode Bottom Bar ---
  navBottomBar: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: '#1a1a2e', paddingTop: 14, paddingHorizontal: 16,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    shadowColor: '#000', shadowOffset: { width: 0, height: -4 }, shadowOpacity: 0.3, shadowRadius: 10, elevation: 10,
    zIndex: 50,
  },
  navBarInfo: { flex: 1 },
  navBarTime: { color: '#fff', fontSize: 28, fontWeight: '800' },
  navBarDist: { color: '#8e8ea0', fontSize: 14, fontWeight: '600', marginTop: 2 },
  navToggleBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.15)',
    justifyContent: 'center', alignItems: 'center', marginRight: 12,
  },
  navExitBtn: {
    backgroundColor: '#EA4335', paddingVertical: 12, paddingHorizontal: 24,
    borderRadius: 24,
  },
  navExitText: { color: '#fff', fontSize: 16, fontWeight: '800' },
  navigationStatusBanner: {
    position: 'absolute', alignSelf: 'center', maxWidth: '88%', minHeight: 38,
    flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 14, paddingVertical: 9,
    borderRadius: 19, backgroundColor: 'rgba(11, 87, 208, 0.94)', zIndex: 45,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.22, shadowRadius: 7, elevation: 7,
  },
  navigationStatusBannerWarning: { backgroundColor: 'rgba(180, 71, 0, 0.96)' },
  navigationStatusText: { flex: 1, color: '#fff', fontSize: 12, fontWeight: '800' },
  navigationRerouteText: { color: '#fff', fontSize: 10, fontWeight: '900', letterSpacing: 0.5 },

  // --- Recenter & Detour Buttons ---
  recenterBtn: {
    position: 'absolute', left: 16,
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.95)',
    paddingVertical: 10, paddingHorizontal: 16,
    borderRadius: 24,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.15, shadowRadius: 6, elevation: 5,
    zIndex: 40,
  },
  recenterText: { color: '#202124', fontSize: 15, fontWeight: '700', marginLeft: 6 },

  detourContainer: {
    position: 'absolute', right: 16,
    alignItems: 'flex-end',
    zIndex: 40,
    gap: 12,
  },
  detourBtn: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.95)',
    paddingVertical: 10, paddingHorizontal: 14,
    borderRadius: 24,
    gap: 6,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.15, shadowRadius: 6, elevation: 5,
  },
  detourText: { color: '#202124', fontSize: 14, fontWeight: '700' },
});
