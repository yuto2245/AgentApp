import { useEffect, useMemo, useState } from 'react';

export default function Map(props) {
  const { q, latitude = 35.681236, longitude = 139.767125, zoom = 12 } = props || {};
  const [center, setCenter] = useState({ lat: latitude, lng: longitude, zoom, q });

  // Recenter when props change
  useEffect(() => {
    setCenter({ lat: latitude, lng: longitude, zoom, q });
  }, [latitude, longitude, zoom, q]);

  // Google Maps embed (no API key required)
  const embedSrc = useMemo(() => {
    const { lat, lng, zoom, q } = center;
    const base = 'https://www.google.com/maps';
    if (q && typeof q === 'string' && q.trim().length > 0) {
      const qs = encodeURIComponent(q.trim());
      return `${base}?q=${qs}&z=${zoom}&output=embed`;
    }
    return `${base}?q=${lat},${lng}&z=${zoom}&output=embed`;
  }, [center]);

  const wrapper = {
    border: '1px solid #e5e7eb',
    borderRadius: 8,
    overflow: 'hidden',
    background: '#fff',
  };

  const header = {
    padding: '10px 12px',
    borderBottom: '1px solid #e5e7eb',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  };

  const badge = {
    fontSize: 12,
    padding: '2px 8px',
    background: '#eef2ff',
    color: '#3730a3',
    borderRadius: 999,
  };

  const meta = { fontSize: 12, color: '#6b7280' };

  const frameBox = { width: '100%', height: 360, border: 'none' };

  return (
    <div style={wrapper}>
      <div style={header}>
        <span style={badge}>Canvas: Google Map</span>
        {center.q ? (
          <span style={meta}>q: {center.q} / zoom: {center.zoom}</span>
        ) : (
          <span style={meta}>
            lat: {center.lat.toFixed(6)} / lng: {center.lng.toFixed(6)} / zoom: {center.zoom}
          </span>
        )}
      </div>
      <iframe
        title="canvas-google-map"
        src={embedSrc}
        style={frameBox}
        loading="lazy"
        referrerPolicy="no-referrer-when-downgrade"
        allowFullScreen
      />
    </div>
  );
}
