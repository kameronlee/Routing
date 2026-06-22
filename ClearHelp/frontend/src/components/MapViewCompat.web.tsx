import React, { forwardRef, useImperativeHandle } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';

type MapViewHandle = {
  animateCamera: (...args: unknown[]) => void;
  animateToRegion: (...args: unknown[]) => void;
  fitToCoordinates: (...args: unknown[]) => void;
};

type MapViewProps = {
  children?: React.ReactNode;
  customMapStyle?: unknown[];
  style?: StyleProp<ViewStyle>;
};

type OverlayProps = {
  children?: React.ReactNode;
  [key: string]: unknown;
};

const noop = () => undefined;

const MapView = forwardRef<MapViewHandle, MapViewProps>(({ children, customMapStyle, style }, ref) => {
  const isDark = Boolean(customMapStyle?.length);
  useImperativeHandle(ref, () => ({
    animateCamera: noop,
    animateToRegion: noop,
    fitToCoordinates: noop,
  }));

  return (
    <View style={[style, styles.map, isDark && styles.mapDark]} accessibilityLabel="Map preview">
      <View pointerEvents="none" style={[styles.message, isDark && styles.messageDark]}>
        <Text style={[styles.title, isDark && styles.titleDark]}>Washington, D.C. route map</Text>
        <Text style={[styles.subtitle, isDark && styles.subtitleDark]}>Interactive map controls are available in the iOS and Android app.</Text>
      </View>
      {children}
    </View>
  );
});

MapView.displayName = 'MapViewCompat';

const HiddenOverlay = (_props: OverlayProps) => null;

export const Circle = HiddenOverlay;
export const Marker = HiddenOverlay;
export const Polygon = HiddenOverlay;
export const Polyline = HiddenOverlay;
export default MapView;

const styles = StyleSheet.create({
  map: {
    alignItems: 'center',
    backgroundColor: '#dceaf5',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  mapDark: { backgroundColor: '#172027' },
  message: {
    alignItems: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.9)',
    borderRadius: 14,
    maxWidth: 360,
    paddingHorizontal: 20,
    paddingVertical: 14,
  },
  messageDark: { backgroundColor: 'rgba(24, 27, 32, 0.94)' },
  subtitle: {
    color: '#5f6368',
    fontSize: 13,
    marginTop: 4,
    textAlign: 'center',
  },
  subtitleDark: { color: '#aeb4bd' },
  title: {
    color: '#202124',
    fontSize: 16,
    fontWeight: '700',
  },
  titleDark: { color: '#f1f3f4' },
});
