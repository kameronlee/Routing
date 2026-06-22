import type { MapCoordinate } from '../api/routingBackend';

const EARTH_RADIUS_M = 6_371_008.8;

export type RouteProgress = {
  closestSegmentIndex: number;
  distanceFromRouteM: number;
  fractionComplete: number;
  remainingDistanceM: number;
  totalDistanceM: number;
};

export function haversineDistanceM(a: MapCoordinate, b: MapCoordinate): number {
  const lat1 = a.latitude * Math.PI / 180;
  const lat2 = b.latitude * Math.PI / 180;
  const deltaLat = lat2 - lat1;
  const deltaLon = (b.longitude - a.longitude) * Math.PI / 180;
  const value = Math.sin(deltaLat / 2) ** 2
    + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(value)));
}

function localMeters(point: MapCoordinate, origin: MapCoordinate) {
  const meanLatitude = (point.latitude + origin.latitude) * Math.PI / 360;
  return {
    x: (point.longitude - origin.longitude) * Math.PI / 180 * EARTH_RADIUS_M * Math.cos(meanLatitude),
    y: (point.latitude - origin.latitude) * Math.PI / 180 * EARTH_RADIUS_M,
  };
}

export function calculateRouteProgress(route: MapCoordinate[], position: MapCoordinate): RouteProgress {
  if (route.length < 2) {
    const distance = route.length === 1 ? haversineDistanceM(route[0], position) : 0;
    return {
      closestSegmentIndex: 0,
      distanceFromRouteM: distance,
      fractionComplete: 0,
      remainingDistanceM: 0,
      totalDistanceM: 0,
    };
  }

  const segmentLengths: number[] = [];
  let totalDistanceM = 0;
  for (let index = 0; index < route.length - 1; index += 1) {
    const length = haversineDistanceM(route[index], route[index + 1]);
    segmentLengths.push(length);
    totalDistanceM += length;
  }

  let closestSegmentIndex = 0;
  let distanceFromRouteM = Number.POSITIVE_INFINITY;
  let completedDistanceM = 0;
  let distanceBeforeSegmentM = 0;

  for (let index = 0; index < route.length - 1; index += 1) {
    const start = localMeters(route[index], position);
    const end = localMeters(route[index + 1], position);
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const squaredLength = dx * dx + dy * dy;
    const projection = squaredLength > 0
      ? Math.max(0, Math.min(1, -(start.x * dx + start.y * dy) / squaredLength))
      : 0;
    const projectedX = start.x + projection * dx;
    const projectedY = start.y + projection * dy;
    const distance = Math.hypot(projectedX, projectedY);

    if (distance < distanceFromRouteM) {
      distanceFromRouteM = distance;
      closestSegmentIndex = index;
      completedDistanceM = distanceBeforeSegmentM + segmentLengths[index] * projection;
    }
    distanceBeforeSegmentM += segmentLengths[index];
  }

  return {
    closestSegmentIndex,
    distanceFromRouteM,
    fractionComplete: totalDistanceM > 0 ? Math.max(0, Math.min(1, completedDistanceM / totalDistanceM)) : 0,
    remainingDistanceM: Math.max(0, totalDistanceM - completedDistanceM),
    totalDistanceM,
  };
}
