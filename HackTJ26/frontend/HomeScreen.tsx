import React, { useState, useEffect, useRef, useMemo } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, Alert, Keyboard, Dimensions, FlatList, ScrollView } from 'react-native';
import MapView, { Circle, Marker, Polyline, Region, Polygon } from 'react-native-maps';
import BottomSheet, { BottomSheetScrollView } from '@gorhom/bottom-sheet';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { MapPin, Navigation, ChevronLeft, Layers, LocateFixed, Map as MapIcon, History, X, Clock, Bike, Footprints, Leaf, Volume2, Sun, Mountain, Armchair, Droplets, Repeat2, Route, Search, Sparkles, Utensils, House, HeartHandshake, GraduationCap, ClipboardCheck, ShieldCheck, Phone } from 'lucide-react-native';
import * as Location from 'expo-location';
import { DEFAULT_ROUTE_PREFERENCES, fetchBackendRoutes, RoutingApiError } from './src/api/routingBackend';
import type { DeparturePreset, DetourBudget, MapCoordinate, RouteComparison, RoutePreferences, RouteProfile, TravelMode } from './src/api/routingBackend';

const INITIAL_REGION = {
  latitude: 38.8895,
  longitude: -76.9833,
  latitudeDelta: 0.05,
  longitudeDelta: 0.05,
};

// 5km x 5km Bounding Box mapped in the backend
const BBOX_COORDS = [
  { latitude: 38.9119, longitude: -77.0121 }, // NW (North, West)
  { latitude: 38.9119, longitude: -76.9545 }, // NE (North, East)
  { latitude: 38.8670, longitude: -76.9545 }, // SE (South, East)
  { latitude: 38.8670, longitude: -77.0121 }, // SW (South, West)
];

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

type SupportCategory = 'all' | 'food' | 'housing' | 'mental' | 'school';

type SupportResource = {
  id: string;
  name: string;
  category: Exclude<SupportCategory, 'all'>;
  coordinate: MapCoordinate;
  distanceLabel: string;
  status: string;
  summary: string;
  action: string;
  confidence: 'High' | 'Medium';
};

type SupportPlan = {
  category: Exclude<SupportCategory, 'all'>;
  urgency: 'Today' | 'This week' | 'Routine';
  title: string;
  plainLanguage: string;
  checklist: string[];
  nextSteps: string[];
  confidence: 'High' | 'Medium' | 'Needs review';
};

const SUPPORT_CATEGORIES: { id: SupportCategory; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'food', label: 'Food' },
  { id: 'housing', label: 'Housing' },
  { id: 'mental', label: 'Mental health' },
  { id: 'school', label: 'School' },
];

const SUPPORT_RESOURCES: SupportResource[] = [
  {
    id: 'food-pantry',
    name: 'Eastside Family Pantry',
    category: 'food',
    coordinate: { latitude: 38.8898, longitude: -76.9838 },
    distanceLabel: '0.4 mi',
    status: 'Open today',
    summary: 'Groceries, SNAP form help, and weekend meal referrals.',
    action: 'Bring ID if available',
    confidence: 'Medium',
  },
  {
    id: 'housing-desk',
    name: 'Family Housing Intake Desk',
    category: 'housing',
    coordinate: { latitude: 38.8945, longitude: -76.9905 },
    distanceLabel: '0.8 mi',
    status: 'Call before going',
    summary: 'Eviction notice triage, shelter intake, and rental-assistance navigation.',
    action: 'Ask about deadline',
    confidence: 'Medium',
  },
  {
    id: 'student-wellness',
    name: 'Student Wellness Center',
    category: 'mental',
    coordinate: { latitude: 38.8847, longitude: -76.9788 },
    distanceLabel: '0.6 mi',
    status: 'Same-day support',
    summary: 'Counselor referral, crisis handoff, and stress support for students.',
    action: 'Talk to a trusted adult',
    confidence: 'High',
  },
  {
    id: 'school-success',
    name: 'School Support Office',
    category: 'school',
    coordinate: { latitude: 38.8867, longitude: -76.9958 },
    distanceLabel: '0.9 mi',
    status: 'Weekdays',
    summary: 'Attendance letters, meal forms, transportation notes, and family liaison help.',
    action: 'Save the notice',
    confidence: 'High',
  },
];

const SAMPLE_NOTICE = 'Your student may lose meal benefits unless the household verification form is returned by Friday. Bring proof of address or income if requested.';

interface OverpassCoord {
  latitude: number;
  longitude: number;
  id: string;
}

// --- Main Home Screen ---
export default function HomeScreen() {
  const insets = useSafeAreaInsets();

  // Search text state
  const [startText, setStartText] = useState('');
  const [destText, setDestText] = useState('');

  // Coordinate state
  const [startCoord, setStartCoord] = useState<MapCoordinate | null>(null);
  const [destinationCoords, setDestinationCoords] = useState<MapCoordinate | null>(null);

  // Autocomplete
  const [activeField, setActiveField] = useState<'start' | 'dest' | null>(null);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  // Route state
  const [standardRoute, setStandardRoute] = useState<MapCoordinate[]>([]);
  const [coolRoute, setCoolRoute] = useState<MapCoordinate[]>([]);
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
  const [originalDestination, setOriginalDestination] = useState<any>(null);

  // Search History
  const [searchHistory, setSearchHistory] = useState<any[]>([]);

  // Support navigator state
  const [selectedSupportCategory, setSelectedSupportCategory] = useState<SupportCategory>('all');
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>('food-pantry');
  const [supportNoticeText, setSupportNoticeText] = useState('');
  const [supportPlan, setSupportPlan] = useState<SupportPlan | null>(null);

  // User Routing Preferences
  const [routePrefs, setRoutePrefs] = useState<RoutePreferences>(DEFAULT_ROUTE_PREFERENCES);

  // Navigation Heading Tracking
  const headingSubRef = useRef<Location.LocationSubscription | null>(null);

  // --- Overpass POI state (benches & water fountains) ---
  const [benches, setBenches] = useState<OverpassCoord[]>([]);
  const [waterFountains, setWaterFountains] = useState<OverpassCoord[]>([]);
  const [isZoomedIn, setIsZoomedIn] = useState(false);
  const [fetchingPOIs, setFetchingPOIs] = useState(false);

  const mapRef = useRef<MapView>(null);
  const homeSheetRef = useRef<BottomSheet>(null);
  const routeSheetRef = useRef<BottomSheet>(null);
  const sheetSnapPoints = useMemo(() => ['9%', '44%', '82%'], []);

  // Track the query text separately to avoid dependency issues
  const [searchQuery, setSearchQuery] = useState('');

  // Debounce timer for Overpass API calls
  const overpassTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const routeWarmupRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    routeWarmupRef.current = fetchBackendRoutes({
      start: DEFAULT_START_COORD,
      destination: DEFAULT_DESTINATION_COORD,
      preferences: DEFAULT_ROUTE_PREFERENCES,
    })
      .then(() => undefined)
      .catch((error) => {
        console.warn('[ROUTE WARMUP] Failed:', error instanceof Error ? error.message : error);
      });
  }, []);

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
    [selectedSupportCategory]
  );

  const selectedResource = useMemo(
    () => SUPPORT_RESOURCES.find(resource => resource.id === selectedResourceId) || visibleSupportResources[0],
    [selectedResourceId, visibleSupportResources]
  );

  const selectSupportCategory = (category: SupportCategory) => {
    setSelectedSupportCategory(category);
    const firstMatch = SUPPORT_RESOURCES.find(resource => category === 'all' || resource.category === category);
    if (firstMatch) {
      setSelectedResourceId(firstMatch.id);
    }
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
      500
    );
  };

  const buildSupportPlan = () => {
    const rawText = supportNoticeText.trim() || SAMPLE_NOTICE;
    if (!supportNoticeText.trim()) {
      setSupportNoticeText(SAMPLE_NOTICE);
    }

    const text = rawText.toLowerCase();
    let category: SupportPlan['category'] = 'school';
    if (/evict|rent|lease|shelter|housing|landlord|utility/.test(text)) {
      category = 'housing';
    } else if (/food|meal|snap|ebt|pantry|hungry|income|verification/.test(text)) {
      category = 'food';
    } else if (/crisis|unsafe|panic|anxiety|depress|counsel|harm|stress/.test(text)) {
      category = 'mental';
    }

    const plans: Record<SupportPlan['category'], SupportPlan> = {
      food: {
        category: 'food',
        urgency: 'Today',
        title: 'Food-benefit notice',
        plainLanguage: 'This looks like a deadline or verification request about food or meal support. The safest next move is to confirm the deadline and collect the documents it asks for.',
        checklist: ['Find the deadline date', 'Keep a photo of the full notice', 'Gather ID, address, or income proof if requested', 'Ask a school liaison or pantry worker to review it'],
        nextSteps: ['Call or visit a food-support desk before the deadline', 'Ask what happens if a document is missing', 'Do not send sensitive information to an unverified number'],
        confidence: 'Medium',
      },
      housing: {
        category: 'housing',
        urgency: 'Today',
        title: 'Housing or eviction notice',
        plainLanguage: 'This may affect where someone can stay. The AI can help organize the notice, but a human housing advocate should review the deadline and rights.',
        checklist: ['Save every page of the notice', 'Circle the date and required action', 'Bring lease, ID, and any court papers', 'Contact a housing intake worker'],
        nextSteps: ['Ask whether there is an appeal or response deadline', 'Do not ignore court or landlord dates', 'Get human review before signing anything'],
        confidence: 'Needs review',
      },
      mental: {
        category: 'mental',
        urgency: 'Today',
        title: 'Wellness or safety concern',
        plainLanguage: 'This sounds like a student wellness concern. If anyone may be in immediate danger, a trusted adult or local emergency service should be involved right away.',
        checklist: ['Stay with the person if it is safe', 'Tell a trusted adult what changed', 'Write down the exact concern', 'Ask for same-day counselor support'],
        nextSteps: ['Use the nearest school or community wellness contact', 'Share only what is needed to get help', 'Let a trained person make the safety decision'],
        confidence: 'Needs review',
      },
      school: {
        category: 'school',
        urgency: 'This week',
        title: 'School support notice',
        plainLanguage: 'This looks like a school form, attendance message, or support notice. The key is to identify what is due, who sent it, and what proof is needed.',
        checklist: ['Find who sent the notice', 'Highlight the due date', 'List forms or proof requested', 'Ask the family liaison or counselor for help'],
        nextSteps: ['Reply through an official school channel', 'Bring the notice to the support office', 'Ask for a plain-language copy if it is confusing'],
        confidence: 'High',
      },
    };

    const plan = plans[category];
    setSupportPlan(plan);
    selectSupportCategory(category);
    const matchingResource = SUPPORT_RESOURCES.find(resource => resource.category === category);
    if (matchingResource) {
      focusSupportResource(matchingResource);
    }
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
      resource.name,
      `Prototype contact step: ${resource.action}. A real version would open a verified phone number or official source link.`
    );
  };

  // Debounced search effect keyed on searchQuery
  useEffect(() => {
    if (searchQuery.length < 3) {
      setSuggestions([]);
      return;
    }

    const timeoutId = setTimeout(async () => {
      console.log('[SEARCH] Fetching results for:', searchQuery);
      setIsSearching(true);
      try {
        // 5x5km BBOX centered on Capitol Hill
        // viewbox=<x1>,<y1>,<x2>,<y2> -> Left(West), Top(North), Right(East), Bottom(South)
        const viewbox = "-77.0121,38.9119,-76.9545,38.8670";
        const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(searchQuery)}&format=jsonv2&viewbox=${viewbox}&bounded=1&addressdetails=1&limit=5`;
        const response = await fetch(url, {
          headers: { 'User-Agent': 'ClearHelpDC/1.0' }
        });
        const data = await response.json();

        // Hard-filter autocomplete results to explicitly prevent out-of-bounds suggestions
        const filteredData = data.filter((d: any) => {
          const lat = parseFloat(d.lat);
          const lon = parseFloat(d.lon);
          return lat <= 38.9119 && lat >= 38.8670 && lon <= -76.9545 && lon >= -77.0121;
        });

        console.log('[SEARCH] Got', filteredData.length, 'valid results');
        setSuggestions(filteredData);
      } catch (e) {
        console.error("[SEARCH] Error:", e);
        setSuggestions([]);
      } finally {
        setIsSearching(false);
      }
    }, 400);

    return () => clearTimeout(timeoutId);
  }, [searchQuery]);

  const handleSuggestionPress = (item: any) => {
    const shortName = item.display_name.split(',')[0];
    const coord = { latitude: parseFloat(item.lat), longitude: parseFloat(item.lon) };

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
    const usingDefaultRoute = !activeStart || !activeEnd;

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
      if (usingDefaultRoute && routeWarmupRef.current) {
        await routeWarmupRef.current;
      }

      const data = await fetchBackendRoutes({
        start: activeStart,
        destination: activeEnd,
        preferences: routePrefs,
      });

      setStandardRoute(data.standardRoute);
      setCoolRoute(data.coolRoute);
      setComparison(data.comparison);

      if (data.coolRoute.length > 0) {
        if (isNavigatingRef.current && followMode) {
          mapRef.current?.animateCamera(
            {
              center: { latitude: activeStart.latitude, longitude: activeStart.longitude },
              pitch: NAV_PITCH,
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
    } catch (err: any) {
      console.error(err);
      const message = err instanceof RoutingApiError
        ? err.message
        : err.message || "Could not calculate routes. Please try different locations.";
      Alert.alert("Route Error", message);
      setComparison(null);
    } finally {
      setLoading(false);
    }
  };

  // --- Navigation Mode ---
  const startNavigation = async () => {
    // Rely exclusively on the routed graph node rather than the raw user input coordinate
    // because the backend snaps the route to the nearest walk-able street node.
    const center = coolRoute.length > 0 ? coolRoute[0] : startCoord;
    if (!center) return;

    // Pre-fetch heading so the intial swoop perfectly aligns with the user's direction
    let initialHeading = 0;
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status === 'granted') {
        const h = await Location.getHeadingAsync();
        initialHeading = h.trueHeading || h.magHeading;
      }
    } catch (e) {
      console.warn("Failed to get initial heading:", e);
    }

    setIsNavigating(true);
    isNavigatingRef.current = true;
    setFollowMode(true);
    routeSheetRef.current?.close();

    mapRef.current?.animateCamera(
      {
        center: { latitude: center.latitude, longitude: center.longitude },
        pitch: NAV_PITCH,
        heading: initialHeading,
        altitude: NAV_ALTITUDE,
      },
      { duration: 1000 }
    );

    // Start heading tracking AFTER animation to prevent interrupting the swoop
    setTimeout(async () => {
      if (!isNavigatingRef.current) return;
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status === 'granted') {
          headingSubRef.current = await Location.watchHeadingAsync((headingObj) => {
            if (mapRef.current) {
              mapRef.current.animateCamera({ heading: headingObj.trueHeading || headingObj.magHeading }, { duration: 100 });
            }
          });
        }
      } catch (e) {
        console.warn("Heading tracking failed:", e);
      }
    }, 1050);
  };

  const exitNavigation = () => {
    setIsNavigating(false);
    isNavigatingRef.current = false;
    setFollowMode(false);

    // Stop heading tracking
    if (headingSubRef.current) {
      headingSubRef.current.remove();
      headingSubRef.current = null;
    }

    mapRef.current?.animateCamera(
      { pitch: 0, heading: 0, zoom: 14, altitude: 5000 },
      { duration: 800 }
    );
    if (coolRoute.length > 0) {
      setTimeout(() => {
        mapRef.current?.fitToCoordinates(coolRoute, {
          edgePadding: { top: 120, right: 60, bottom: Dimensions.get('window').height * 0.5, left: 60 },
          animated: true,
        });
      }, 850);
    }
    routeSheetRef.current?.snapToIndex(SHEET_MID_INDEX);
  };

  const toggleFollowMode = async () => {
    const newFollow = !followMode;
    setFollowMode(newFollow);
    if (newFollow) {
      const center = coolRoute.length > 0 ? coolRoute[0] : startCoord;
      if (center) {
        mapRef.current?.animateCamera(
          {
            center: { latitude: center.latitude, longitude: center.longitude },
            pitch: NAV_PITCH,
            altitude: NAV_ALTITUDE,
          },
          { duration: 600 }
        );
      }

      // Re-start heading tracking AFTER the main animation finishes
      setTimeout(async () => {
        // use local closure check since state might not be updated here? Actually relying on a ref would be better
        // but checking the new state variable helps slightly
        try {
          if (!headingSubRef.current) {
             const { status } = await Location.requestForegroundPermissionsAsync();
             if (status === 'granted') {
               headingSubRef.current = await Location.watchHeadingAsync((headingObj) => {
                 if (mapRef.current) {
                   mapRef.current.animateCamera({ heading: headingObj.trueHeading || headingObj.magHeading }, { duration: 100 });
                 }
               });
             }
          }
        } catch (e) {}
      }, 650);
    } else {
      // Stop heading tracking in free view so the user can pan/rotate freely
      if (headingSubRef.current) {
        headingSubRef.current.remove();
        headingSubRef.current = null;
      }
      mapRef.current?.animateCamera(
        { pitch: 0, heading: 0, altitude: 2000 },
        { duration: 600 }
      );
    }
  };

  const handleMapDrag = () => {
    if (isNavigating && followMode) {
      setFollowMode(false);
      // Stop heading tracking so user can pan freely
      if (headingSubRef.current) {
        headingSubRef.current.remove();
        headingSubRef.current = null;
      }
    }
  };

  const handleDetour = (type: 'bench' | 'water') => {
    const pois = type === 'bench' ? benches : waterFountains;
    if (pois.length === 0) {
      Alert.alert("No Data", `No ${type}s loaded in this area. Try zooming out slightly to load POIs.`);
      return;
    }

    // Switch to 2D bird's-eye view automatically
    if (followMode) {
      setFollowMode(false);
      if (headingSubRef.current) {
        headingSubRef.current.remove();
        headingSubRef.current = null;
      }
      mapRef.current?.animateCamera(
        { pitch: 0, heading: 0, altitude: 2000 },
        { duration: 600 }
      );
    }

    // NEW HEURISTIC: Find the POI that is closest to our CURRENT POSITION
    // but also biases towards POIs that are further along our path.
    // If we have a coolRoute, we use its first coordinate (where we are currently simulated to be)
    // as our starting point, rather than the raw startCoord (which might be null or outdated).
    const currentLoc = (coolRoute.length > 0) ? coolRoute[0] : (startCoord || { latitude: 38.8906, longitude: -76.9803 });
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
    if (!originalDestination) {
      setOriginalDestination({ coord: destinationCoords, text: destText });
    }

    const newDest = { latitude: bestPoi.latitude, longitude: bestPoi.longitude };
    setDestinationCoords(newDest);
    setDestText(`${type === 'bench' ? 'Rest Bench' : 'Water Fountain'}`);

    // Re-fetch route with new destination (from our current simulated location)
    fetchDualRoute(currentLoc, newDest);
  };

  const handleResumeJourney = () => {
    if (!originalDestination) return;

    setDestinationCoords(originalDestination.coord);
    setDestText(originalDestination.text);

    // Clear the saved destination so we exit detour mode
    const oldDest = originalDestination.coord;
    setOriginalDestination(null);

    fetchDualRoute(startCoord || undefined, oldDest);
  };

  const hasSuggestions = suggestions.length > 0;
  const enabledPoiLabel = routePrefs.showBenches && routePrefs.showWater
    ? 'benches & water'
    : routePrefs.showBenches
      ? 'benches'
      : routePrefs.showWater
        ? 'water'
        : '';
  const floatingControlBottom = insets.bottom + 96;

  const renderProfileIcon = (profile: RouteProfile, color: string) => {
    if (profile === 'coolest') return <Sun size={17} color={color} />;
    if (profile === 'quiet') return <Volume2 size={17} color={color} />;
    if (profile === 'green') return <Leaf size={17} color={color} />;
    if (profile === 'fastest') return <Navigation size={17} color={color} />;
    return <Route size={17} color={color} />;
  };

  const renderSupportIcon = (category: SupportResource['category'], color: string, size = 17) => {
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
        showsUserLocation={!isNavigating}
        onRegionChangeComplete={handleRegionChange}
        onPanDrag={handleMapDrag}
        pitchEnabled={true}
        rotateEnabled={true}
      >
        {/* Persistent Operating Boundary Box */}
        <Polygon
          coordinates={BBOX_COORDS}
          strokeColor="rgba(255, 67, 53, 0.4)"
          strokeWidth={4}
          lineDashPattern={[10, 10]}
          fillColor="transparent"
        />

        {!isNavigating && visibleSupportResources.map((resource) => {
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
          <Polyline coordinates={standardRoute} strokeColor="#EA4335" strokeWidth={4} />
        )}
        {/* Cool Route (solid blue) */}
        {coolRoute.length > 0 && (
          <Polyline coordinates={coolRoute} strokeColor="#4285f4" strokeWidth={6} />
        )}
        {/* Route start/end markers */}
        {coolRoute.length > 0 && (
          <>
            <Marker coordinate={coolRoute[0]} pinColor="green" title="Start" />
            <Marker coordinate={coolRoute[coolRoute.length - 1]} pinColor="red" title="End" />
          </>
        )}

        {/* ---- Simulated User Location (navigation mode) ---- */}
        {isNavigating && coolRoute.length > 0 && (
          <Marker coordinate={coolRoute[0]} anchor={{ x: 0.5, y: 0.5 }}>
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
          style={[styles.collapsedBar, { top: insets.top + 10 }]}
          onPress={() => setIsExpanded(true)}
          activeOpacity={0.9}
        >
          <View style={styles.collapsedInner}>
            <View style={styles.appIcon}>
              <HeartHandshake size={18} color="#fff" />
            </View>
            <Text style={styles.collapsedText}>Search help near you</Text>
            <View style={styles.profileCircle}>
              <Text style={styles.profileInitial}>C</Text>
            </View>
          </View>
        </TouchableOpacity>
      ) : (
        /* -- Expanded full-screen search overlay -- */
        <View style={[styles.expandedOverlay, { paddingTop: insets.top + 10 }]}>
          <View style={styles.expandedCard}>
            <View style={styles.directionsHeader}>
              <TouchableOpacity
                onPress={() => { setIsExpanded(false); setSuggestions([]); setSearchQuery(''); setActiveField(null); }}
                style={styles.backBtn}
              >
                <ChevronLeft size={24} color="#202124" />
              </TouchableOpacity>
              <Text style={styles.directionsTitle}>Directions</Text>
              <TouchableOpacity onPress={swapRouteEndpoints} style={styles.headerIconBtn} activeOpacity={0.75}>
                <Repeat2 size={19} color="#5f6368" />
              </TouchableOpacity>
            </View>

            <View style={styles.expandedRow}>
              <View style={styles.inputsCol}>
                <View style={[styles.fieldRow, activeField === 'start' && styles.fieldRowActive]}>
                  <View style={styles.dotBlue} />
                  <TextInput
                    style={styles.fieldInput}
                    placeholder="Starting point"
                    placeholderTextColor="#9aa0a6"
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
                <View style={[styles.fieldRow, activeField === 'dest' && styles.fieldRowActive]}>
                  <View style={styles.dotRed} />
                  <TextInput
                    style={styles.fieldInput}
                    placeholder="Destination"
                    placeholderTextColor="#9aa0a6"
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
                style={[styles.travelModeTab, routePrefs.travelMode === 'walk' && styles.travelModeTabActive]}
                onPress={() => setTravelMode('walk')}
                activeOpacity={0.75}
              >
                <Footprints size={18} color={routePrefs.travelMode === 'walk' ? '#1967d2' : '#5f6368'} />
                <Text style={[styles.travelModeText, routePrefs.travelMode === 'walk' && styles.travelModeTextActive]}>Walk</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.travelModeTab, routePrefs.travelMode === 'bike' && styles.travelModeTabActive]}
                onPress={() => setTravelMode('bike')}
                activeOpacity={0.75}
              >
                <Bike size={18} color={routePrefs.travelMode === 'bike' ? '#1967d2' : '#5f6368'} />
                <Text style={[styles.travelModeText, routePrefs.travelMode === 'bike' && styles.travelModeTextActive]}>Bike</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Suggestions or History list */}
          {(hasSuggestions || (searchHistory.length > 0 && activeField)) ? (
            <FlatList
              data={hasSuggestions ? suggestions : searchHistory}
              keyExtractor={(item, i) => String(item.place_id || item.osm_id || i)}
              keyboardShouldPersistTaps="always"
              style={styles.suggestionsList}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={styles.suggestionRow}
                  onPress={() => handleSuggestionPress(item)}
                  activeOpacity={0.6}
                >
                  <View style={styles.suggestionIcon}>
                    {hasSuggestions ? <MapPin size={18} color="#5f6368" /> : <History size={18} color="#5f6368" />}
                  </View>
                  <View style={styles.suggestionTextCol}>
                    <Text style={styles.suggestionMain} numberOfLines={1}>
                      {item.display_name.split(',')[0]}
                    </Text>
                    <Text style={styles.suggestionSub} numberOfLines={2}>
                      {item.display_name}
                    </Text>
                  </View>
                </TouchableOpacity>
              )}
            />
          ) : (
            <ScrollView
              style={styles.optionsScroll}
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

              <View style={styles.optionSection}>
                <Text style={styles.sectionTitle}>Route profile</Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.profileRow}>
                  {ROUTE_PROFILES.map(profile => {
                    const selected = routePrefs.profile === profile.id;
                    const iconColor = selected ? '#1967d2' : '#5f6368';
                    return (
                      <TouchableOpacity
                        key={profile.id}
                        style={[styles.profileChip, selected && styles.profileChipActive]}
                        onPress={() => updateRoutePref('profile', profile.id)}
                        activeOpacity={0.75}
                      >
                        <View style={[styles.profileIcon, selected && styles.profileIconActive]}>
                          {renderProfileIcon(profile.id, iconColor)}
                        </View>
                        <Text style={[styles.profileLabel, selected && styles.profileLabelActive]}>{profile.label}</Text>
                        <Text style={styles.profileSub}>{profile.sublabel}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </ScrollView>
              </View>

              <View style={styles.optionSection}>
                <View style={styles.sectionHeaderRow}>
                  <Text style={styles.sectionTitle}>Leave</Text>
                  <Clock size={16} color="#5f6368" />
                </View>
                <View style={styles.compactChipRow}>
                  {DEPARTURE_OPTIONS.map(option => {
                    const selected = routePrefs.departurePreset === option.id;
                    return (
                      <TouchableOpacity
                        key={option.id}
                        style={[styles.compactChip, selected && styles.compactChipActive]}
                        onPress={() => updateRoutePref('departurePreset', option.id)}
                        activeOpacity={0.75}
                      >
                        <Text style={[styles.compactChipText, selected && styles.compactChipTextActive]}>{option.label}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>

              <View style={styles.optionSection}>
                <Text style={styles.sectionTitle}>Comfort priorities</Text>
                <View style={styles.toggleGrid}>
                  <TouchableOpacity
                    style={[styles.toggleTile, routePrefs.cooling && styles.toggleTileActive]}
                    onPress={() => toggleRoutePref('cooling')}
                    activeOpacity={0.75}
                  >
                    <Sun size={18} color={routePrefs.cooling ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, routePrefs.cooling && styles.toggleTitleActive]}>Max shade</Text>
                      <Text style={styles.toggleSub}>UTCI</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, routePrefs.quiet && styles.toggleTileActive]}
                    onPress={() => toggleRoutePref('quiet')}
                    activeOpacity={0.75}
                  >
                    <Volume2 size={18} color={routePrefs.quiet ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, routePrefs.quiet && styles.toggleTitleActive]}>Quiet streets</Text>
                      <Text style={styles.toggleSub}>Traffic</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, routePrefs.scenic && styles.toggleTileActive]}
                    onPress={() => toggleRoutePref('scenic')}
                    activeOpacity={0.75}
                  >
                    <Leaf size={18} color={routePrefs.scenic ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, routePrefs.scenic && styles.toggleTitleActive]}>Green blocks</Text>
                      <Text style={styles.toggleSub}>Canopy</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, routePrefs.avoidHills && styles.toggleTileActive]}
                    onPress={() => toggleRoutePref('avoidHills')}
                    activeOpacity={0.75}
                  >
                    <Mountain size={18} color={routePrefs.avoidHills ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, routePrefs.avoidHills && styles.toggleTitleActive]}>Flatter</Text>
                      <Text style={styles.toggleSub}>Slope</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, routePrefs.preferFast && styles.toggleTileActive]}
                    onPress={() => toggleRoutePref('preferFast')}
                    activeOpacity={0.75}
                  >
                    <Navigation size={18} color={routePrefs.preferFast ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, routePrefs.preferFast && styles.toggleTitleActive]}>Keep short</Text>
                      <Text style={styles.toggleSub}>Time</Text>
                    </View>
                  </TouchableOpacity>
                </View>
              </View>

              <View style={styles.optionSection}>
                <Text style={styles.sectionTitle}>Detour budget</Text>
                <View style={styles.budgetRow}>
                  {DETOUR_OPTIONS.map(option => {
                    const selected = routePrefs.detourBudget === option.id;
                    return (
                      <TouchableOpacity
                        key={option.id}
                        style={[styles.budgetChip, selected && styles.budgetChipActive]}
                        onPress={() => updateRoutePref('detourBudget', option.id)}
                        activeOpacity={0.75}
                      >
                        <Text style={[styles.budgetLabel, selected && styles.budgetLabelActive]}>{option.label}</Text>
                        <Text style={styles.budgetSub}>{option.sublabel}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>

              <View style={styles.optionSection}>
                <Text style={styles.sectionTitle}>Stops and alternatives</Text>
                <View style={styles.toggleGrid}>
                  <TouchableOpacity
                    style={[styles.toggleTile, routePrefs.showBenches && styles.toggleTileActive]}
                    onPress={() => toggleRoutePref('showBenches')}
                    activeOpacity={0.75}
                  >
                    <Armchair size={18} color={routePrefs.showBenches ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, routePrefs.showBenches && styles.toggleTitleActive]}>Benches</Text>
                      <Text style={styles.toggleSub}>On map</Text>
                    </View>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.toggleTile, routePrefs.showWater && styles.toggleTileActive]}
                    onPress={() => toggleRoutePref('showWater')}
                    activeOpacity={0.75}
                  >
                    <Droplets size={18} color={routePrefs.showWater ? '#1967d2' : '#5f6368'} />
                    <View style={styles.toggleTextCol}>
                      <Text style={[styles.toggleTitle, routePrefs.showWater && styles.toggleTitleActive]}>Water</Text>
                      <Text style={styles.toggleSub}>On map</Text>
                    </View>
                  </TouchableOpacity>
                </View>
                <View style={styles.compactChipRow}>
                  {CANDIDATE_OPTIONS.map(count => {
                    const selected = routePrefs.maxCandidates === count;
                    return (
                      <TouchableOpacity
                        key={count}
                        style={[styles.compactChip, selected && styles.compactChipActive]}
                        onPress={() => updateRoutePref('maxCandidates', count)}
                        activeOpacity={0.75}
                      >
                        <Text style={[styles.compactChipText, selected && styles.compactChipTextActive]}>{count} route{count > 1 ? 's' : ''}</Text>
                      </TouchableOpacity>
                    );
                  })}
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
          backgroundStyle={styles.sheetBg}
          handleIndicatorStyle={styles.sheetHandle}
        >
          <BottomSheetScrollView
            contentContainerStyle={[styles.supportHomePanelContent, { paddingBottom: insets.bottom + 24 }]}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
          <View style={styles.supportPanelHeader}>
            <View>
              <Text style={styles.supportEyebrow}>ClearHelp DC | students and caregivers</Text>
              <Text style={styles.supportTitle}>Turn a confusing notice into a plan</Text>
            </View>
            <View style={styles.aiBadge}>
              <Sparkles size={14} color="#1967d2" />
              <Text style={styles.aiBadgeText}>AI draft</Text>
            </View>
          </View>

          <View style={styles.noticeInputWrap}>
            <Search size={17} color="#5f6368" />
            <TextInput
              style={styles.noticeInput}
              placeholder="Paste a notice or type what happened"
              placeholderTextColor="#8a9099"
              value={supportNoticeText}
              onChangeText={setSupportNoticeText}
              multiline
            />
            <TouchableOpacity style={styles.explainBtn} onPress={buildSupportPlan} activeOpacity={0.8}>
              <Sparkles size={15} color="#fff" />
            </TouchableOpacity>
          </View>

          <View style={styles.categoryRow}>
            {SUPPORT_CATEGORIES.map(category => {
              const selected = selectedSupportCategory === category.id;
              return (
                <TouchableOpacity
                  key={category.id}
                  style={[styles.categoryChip, selected && styles.categoryChipActive]}
                  onPress={() => selectSupportCategory(category.id)}
                  activeOpacity={0.75}
                >
                  <Text style={[styles.categoryText, selected && styles.categoryTextActive]}>{category.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.homeCardsRow}>
            {supportPlan && (
              <View style={[styles.homeInfoCard, styles.planCard]}>
                <View style={styles.planHeaderRow}>
                  <View style={styles.urgencyPill}>
                    <Clock size={12} color="#a14200" />
                    <Text style={styles.urgencyText}>{supportPlan.urgency}</Text>
                  </View>
                  <Text style={styles.confidenceText}>{supportPlan.confidence}</Text>
                </View>
                <Text style={styles.planTitle}>{supportPlan.title}</Text>
                <Text style={styles.planBody} numberOfLines={3}>{supportPlan.plainLanguage}</Text>
                <View style={styles.checklistPreview}>
                  {supportPlan.checklist.slice(0, 3).map(item => (
                    <View key={item} style={styles.checkRow}>
                      <ClipboardCheck size={13} color="#137333" />
                      <Text style={styles.checkText} numberOfLines={1}>{item}</Text>
                    </View>
                  ))}
                </View>
                <View style={styles.guardrailRow}>
                  <ShieldCheck size={13} color="#5f6368" />
                  <Text style={styles.guardrailText}>Human review for eligibility, safety, legal, or medical decisions</Text>
                </View>
              </View>
            )}

            {visibleSupportResources.map(resource => {
              const selected = selectedResource?.id === resource.id;
              return (
                <TouchableOpacity
                  key={resource.id}
                  style={[styles.homeInfoCard, selected && styles.resourceCardSelected]}
                  onPress={() => focusSupportResource(resource)}
                  activeOpacity={0.85}
                >
                  <View style={styles.resourceTopRow}>
                    <View style={[styles.resourceIconWrap, selected && styles.resourceIconWrapSelected]}>
                      {renderSupportIcon(resource.category, selected ? '#fff' : '#1967d2', 18)}
                    </View>
                    <Text style={styles.resourceDistance}>{resource.distanceLabel}</Text>
                  </View>
                  <Text style={styles.resourceName} numberOfLines={1}>{resource.name}</Text>
                  <Text style={styles.resourceStatus}>{resource.status}</Text>
                  <Text style={styles.resourceSummary} numberOfLines={2}>{resource.summary}</Text>
                  <Text style={styles.resourceConfidence}>Sample directory - {resource.confidence} confidence</Text>
                  <View style={styles.resourceActions}>
                    <TouchableOpacity style={styles.resourceActionBtn} onPress={() => contactSupportResource(resource)} activeOpacity={0.75}>
                      <Phone size={13} color="#1967d2" />
                      <Text style={styles.resourceActionText}>Call</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={[styles.resourceActionBtn, styles.primaryResourceAction]} onPress={() => routeToSupportResource(resource)} activeOpacity={0.75}>
                      <Navigation size={13} color="#fff" />
                      <Text style={styles.primaryResourceActionText}>Go</Text>
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

      {/* ---- GO FAB ---- */}
      {!isExpanded && !comparison && !isNavigating && (
        <TouchableOpacity
          style={[styles.goFab, { bottom: floatingControlBottom }]}
          onPress={() => setIsExpanded(true)}
          activeOpacity={0.85}
        >
          <Navigation size={22} color="#fff" />
          <Text style={styles.goFabText}>Route</Text>
        </TouchableOpacity>
      )}

      {/* ---- Navigation Detour Buttons / Resume Journey ---- */}
      {isNavigating && (originalDestination || routePrefs.showBenches || routePrefs.showWater) && (
        <View style={[styles.detourContainer, { top: insets.top + 20 }]}>
          {originalDestination ? (
            <TouchableOpacity style={[styles.detourBtn, { backgroundColor: '#e8f0fe', borderColor: '#4285f4', borderWidth: 2 }]} onPress={handleResumeJourney} activeOpacity={0.8}>
              <Text style={styles.detourEmoji}>↩️</Text>
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

      {/* ---- Navigation Mode Bottom Bar ---- */}
      {isNavigating && (
        <View style={[styles.navBottomBar, { paddingBottom: insets.bottom + 10 }]}>
          <View style={styles.navBarInfo}>
            <Text style={styles.navBarTime}>
              {comparison ? `${Math.round(comparison.cool_duration_seconds / 60)} min` : '--'}
            </Text>
            <Text style={styles.navBarDist}>
              {comparison ? `${(comparison.cool_total_meters / 1609.34).toFixed(2)} mi` : ''}
              {originalDestination ? ' (to detour)' : ''}
            </Text>
          </View>
          <TouchableOpacity
            style={styles.navToggleBtn}
            onPress={toggleFollowMode}
            activeOpacity={0.8}
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
          <View style={styles.loadingBox}>
            <ActivityIndicator size="large" color="#4285f4" />
            <Text style={styles.loadingText}>Calculating routes...</Text>
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
          backgroundStyle={styles.sheetBg}
          handleIndicatorStyle={styles.sheetHandle}
        >
          <BottomSheetScrollView contentContainerStyle={styles.sheetContent}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
              <Text style={[styles.sheetTitle, { marginBottom: 0 }]}>Route Comparison</Text>
              <TouchableOpacity onPress={() => routeSheetRef.current?.snapToIndex(SHEET_COLLAPSED_INDEX)} style={{ padding: 4 }}>
                <X size={24} color="#5f6368" />
              </TouchableOpacity>
            </View>
            <View style={styles.compRow}>
              <View style={[styles.statBlock, styles.statGray]}>
                <Text style={styles.statLabel}>Standard</Text>
                <Text style={styles.statVal}>{(comparison.standard_total_meters / 1609.34).toFixed(2)} mi</Text>
                <Text style={styles.statSub}>Score: {comparison.standard_shade_score.toFixed(0)} / 100</Text>
              </View>
              <View style={[styles.statBlock, styles.statGreen]}>
                <Text style={[styles.statLabel, { color: '#137333' }]}>Optimized</Text>
                <Text style={[styles.statVal, { color: '#137333' }]}>{(comparison.cool_total_meters / 1609.34).toFixed(2)} mi</Text>
                <Text style={[styles.statSub, { color: '#137333' }]}>Score: {comparison.cool_shade_score.toFixed(0)} / 100</Text>
              </View>
            </View>
            <View style={{ flexDirection: 'row', gap: 12, marginBottom: 14 }}>
              <View style={[styles.metricCard, { flex: 1, marginBottom: 0 }]}>
                <Text style={styles.metricText}>
                  <Text style={[styles.hl, { color: '#34a853' }]}>{comparison.cool_mean_utci.toFixed(1)}</Text> mean UTCI
                </Text>
              </View>
              <View style={[styles.metricCard, { flex: 1, marginBottom: 0 }]}>
                <Text style={styles.metricText}>
                  <Text style={styles.hl}>{comparison.cool_max_utci.toFixed(1)}</Text> max UTCI
                </Text>
              </View>
            </View>
            <View style={styles.metricCard}>
              <Text style={styles.metricText}>
                Extra distance: <Text style={styles.hl}>{Math.round(comparison.extra_distance_meters)} m</Text>
                {'  '}Shade: <Text style={styles.hl}>{comparison.shade_multiplier}x</Text>
              </Text>
            </View>
            <View style={styles.metricGrid}>
              <View style={styles.miniMetric}>
                <Text style={styles.miniMetricLabel}>Scenic</Text>
                <Text style={styles.miniMetricValue}>{Math.round(comparison.scenic_score * 100)}</Text>
              </View>
              <View style={styles.miniMetric}>
                <Text style={styles.miniMetricLabel}>Quiet</Text>
                <Text style={styles.miniMetricValue}>{Math.round(Math.max(0, 1 - comparison.noise_score) * 100)}</Text>
              </View>
              <View style={styles.miniMetric}>
                <Text style={styles.miniMetricLabel}>Slope</Text>
                <Text style={styles.miniMetricValue}>{(comparison.slope_penalty * 100).toFixed(1)}%</Text>
              </View>
              <View style={styles.miniMetric}>
                <Text style={styles.miniMetricLabel}>Heat dose</Text>
                <Text style={styles.miniMetricValue}>{comparison.cool_heat_dose.toFixed(1)}</Text>
              </View>
            </View>
            <Text style={styles.candidateText}>
              {comparison.route_candidate_count} backend candidate{comparison.route_candidate_count === 1 ? '' : 's'} evaluated
            </Text>
            {comparison.warnings.length > 0 && (
              <View style={styles.warningCard}>
                {comparison.warnings.map((warning, index) => (
                  <Text key={`${warning}-${index}`} style={styles.warningText}>{warning}</Text>
                ))}
              </View>
            )}
            {!isNavigating && (
              <TouchableOpacity style={styles.navBtn} onPress={startNavigation}>
                <Navigation size={18} color="#fff" style={{ marginRight: 8 }} />
                <Text style={styles.navBtnText}>Start Navigation</Text>
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
  supportEyebrow: { fontSize: 12, fontWeight: '800', color: '#1967d2', marginBottom: 2 },
  supportTitle: { fontSize: 19, fontWeight: '800', color: '#202124', maxWidth: 250, lineHeight: 24 },
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
  planCard: { width: 290, backgroundColor: '#fffaf2', borderColor: '#fad8a8' },
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
  checklistPreview: { gap: 5, marginBottom: 9 },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  checkText: { flex: 1, fontSize: 12, fontWeight: '700', color: '#3c4043' },
  guardrailRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6, paddingTop: 8, borderTopWidth: 1, borderTopColor: '#f2ddc4' },
  guardrailText: { flex: 1, fontSize: 11, lineHeight: 15, color: '#5f6368', fontWeight: '600' },
  resourceCardSelected: { backgroundColor: '#e8f0fe', borderColor: '#4285f4' },
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

  // --- Suggestions (full-screen list like Google Maps) ---
  suggestionsList: {
    flex: 1, marginTop: 0, backgroundColor: '#fff',
    borderBottomLeftRadius: 16, borderBottomRightRadius: 16,
  },
  suggestionRow: {
    flexDirection: 'row', alignItems: 'center',
    paddingVertical: 14, paddingHorizontal: 18,
    borderBottomWidth: 1, borderBottomColor: '#f1f3f4',
    backgroundColor: '#fff',
  },
  suggestionIcon: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: '#f1f3f4',
    justifyContent: 'center', alignItems: 'center', marginRight: 14,
  },
  suggestionTextCol: { flex: 1 },
  suggestionMain: { fontSize: 15, fontWeight: '500', color: '#202124' },
  suggestionSub: { fontSize: 13, color: '#70757a', marginTop: 2 },

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

  // --- GO FAB ---
  goFab: {
    position: 'absolute', right: 20, width: 60, height: 60, borderRadius: 30,
    backgroundColor: '#4285f4', justifyContent: 'center', alignItems: 'center',
    shadowColor: '#4285f4', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.4, shadowRadius: 8, elevation: 8,
    zIndex: 15,
  },
  goFabText: { color: '#fff', fontSize: 10, fontWeight: '800', marginTop: 1 },

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
  sheetContent: { padding: 24 },
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
  candidateText: { fontSize: 12, fontWeight: '700', color: '#70757a', textAlign: 'center', marginBottom: 14 },
  warningCard: { backgroundColor: '#fff8e1', padding: 12, borderRadius: 12, borderWidth: 1, borderColor: '#fbbc04', marginBottom: 14 },
  warningText: { fontSize: 12, color: '#5f3b00', lineHeight: 17 },
  navBtn: {
    flexDirection: 'row', backgroundColor: '#4285f4', padding: 16, borderRadius: 28,
    alignItems: 'center', justifyContent: 'center', marginTop: 8,
    shadowColor: '#4285f4', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.3, shadowRadius: 8, elevation: 6,
  },
  navBtnText: { color: 'white', fontSize: 17, fontWeight: '700' },

  // --- Simulated Location Marker ---
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
  detourEmoji: { fontSize: 16, marginRight: 6 },
  detourText: { color: '#202124', fontSize: 14, fontWeight: '700' },
});
