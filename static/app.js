/**
 * TraceSpot Frontend Application (app.js) - Phase 2
 * Natural-Language Geospatial Search & Multi-Stop Itinerary on OpenStreetMap
 * Inspired by ACL 2025 "SPOT"
 */

// --- Global State ---
let map = null;
let currentBasemap = null;
let markersClusterGroup = null;
let relationLinesGroup = null;
let isochroneLayerGroup = null;
let itineraryRouteLayerGroup = null;

let currentItineraryData = null;
let currentItineraryIndex = 0;
let lastSearchResults = [];
let lastSearchQueryObj = null;
let lastSearchData = null;
let evalChartInstance = null;
let progressInterval = null;

// Tile Layers - 100% Free OpenStreetMap & Esri (NO API keys required)
const TILE_LAYERS = {
  osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    subdomains: ['a', 'b', 'c'],
    maxZoom: 19
  }),
  dark: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    subdomains: ['a', 'b', 'c'],
    className: 'dark-tile',
    maxZoom: 19
  }),
  satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    maxZoom: 19
  })
};
TILE_LAYERS.light = TILE_LAYERS.osm;

// --- Custom Map Markers ---
function createCustomPin(color = '#6366f1', label = '') {
  return L.divIcon({
    className: 'custom-map-pin',
    html: `
      <div style="position: relative; width: 28px; height: 36px; filter: drop-shadow(0 2px 5px rgba(0,0,0,0.5));">
        <svg viewBox="0 0 24 32" width="28" height="36" fill="none">
          <path d="M12 0C5.37 0 0 5.37 0 12C0 21 12 32 12 32C12 32 24 21 24 12C24 5.37 18.63 0 12 0Z" fill="${color}"/>
          <circle cx="12" cy="11" r="5" fill="#ffffff" fill-opacity="0.9"/>
        </svg>
        ${label !== '' ? `<div style="position: absolute; top: 4px; left: 0; width: 28px; text-align: center; font-size: 10px; font-weight: 800; color: #1e1b4b; font-family: Inter, sans-serif;">${label}</div>` : ''}
      </div>
    `,
    iconSize: [28, 36],
    iconAnchor: [14, 36],
    popupAnchor: [0, -32]
  });
}

// --- Initialize App on DOM Ready ---
document.addEventListener('DOMContentLoaded', () => {
  if (window.location.protocol === 'file:') {
    const banner = document.createElement('div');
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#b91c1c;color:#fff;padding:12px;text-align:center;font-weight:bold;font-size:14px;box-shadow:0 4px 12px rgba(0,0,0,0.5);';
    banner.innerHTML = '⚠️ TraceSpot must be accessed via the FastAPI server at <a href="http://127.0.0.1:8000" style="text-decoration:underline;color:#fef08a;">http://127.0.0.1:8000</a>. Please start the server with <code>python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000</code>.';
    document.body.prepend(banner);
  }
  initMap();
  setupUIEventListeners();
  loadSearchHistory();
  loadSavedSpots();
  loadMetricsData();
});

// --- Map Initialization ---
function initMap() {
  map = L.map('map', {
    zoomControl: false,
    layers: [TILE_LAYERS.dark]
  }).setView([52.5200, 13.4050], 13);

  currentBasemap = 'dark';
  const mapEl = document.getElementById('map');
  if (mapEl) mapEl.classList.add('dark-mode-map');
  L.control.zoom({ position: 'bottomright' }).addTo(map);

  markersClusterGroup = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 40,
    spiderfyOnMaxZoom: true
  });
  map.addLayer(markersClusterGroup);

  relationLinesGroup = L.layerGroup().addTo(map);
  isochroneLayerGroup = L.layerGroup().addTo(map);
  itineraryRouteLayerGroup = L.layerGroup().addTo(map);
}

// --- UI Event Handlers ---
function setupUIEventListeners() {
  // Search Form Submit
  const searchForm = document.getElementById('searchForm');
  searchForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const query = document.getElementById('queryInput').value.trim();
    if (query) {
      performSearch(query);
    }
  });

  // Example Chips
  document.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.getAttribute('data-query');
      document.getElementById('queryInput').value = q;
      performSearch(q);
    });
  });

  // Mode Toggle (Baseline vs Model)
  const toggle = document.getElementById('forceBaselineToggle');
  const label = document.getElementById('parserLabel');
  const indicator = document.getElementById('toggleIndicator');
  toggle.addEventListener('change', () => {
    if (toggle.checked) {
      label.textContent = 'Rule Baseline';
      label.className = 'ml-1.5 text-amber-300 font-medium';
      indicator.className = 'w-3 h-3 bg-amber-400 rounded-full transform translate-x-3 transition';
    } else {
      label.textContent = 'Fine-Tuned T5';
      label.className = 'ml-1.5 text-indigo-300 font-medium';
      indicator.className = 'w-3 h-3 bg-brand-400 rounded-full transform translate-x-0 transition';
    }
  });

  // Walking Reach Slider (Feature 1 Live Control)
  const walkingSlider = document.getElementById('walkingSlider');
  const walkingSliderVal = document.getElementById('walkingSliderVal');
  const walkingSliderSpeed = document.getElementById('walkingSliderSpeed');
  if (walkingSlider) {
    walkingSlider.addEventListener('input', () => {
      const val = parseInt(walkingSlider.value);
      if (walkingSliderVal) walkingSliderVal.textContent = `${val} min`;
      if (walkingSliderSpeed) walkingSliderSpeed.textContent = `~${Math.round(val * 83.33)} m @ 5 km/h`;
    });
    walkingSlider.addEventListener('change', () => {
      const val = parseInt(walkingSlider.value);
      const query = document.getElementById('queryInput').value.trim();
      if (query) {
        performSearch(query, val);
      }
    });
  }

  // Itinerary Alternative Tabs (Feature 2)
  document.querySelectorAll('.itin-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.getAttribute('data-index') || '0');
      if (currentItineraryData) {
        renderItinerary(currentItineraryData, idx);
      }
    });
  });

  // Export Itinerary Buttons (Feature 2)
  const exportGeoJsonBtn = document.getElementById('exportItinGeoJsonBtn');
  if (exportGeoJsonBtn) {
    exportGeoJsonBtn.addEventListener('click', exportItineraryGeoJSON);
  }
  const exportTextBtn = document.getElementById('exportItinTextBtn');
  if (exportTextBtn) {
    exportTextBtn.addEventListener('click', exportItineraryText);
  }

  // Basemap Switcher
  const btnOsm = document.getElementById('bmOSM') || document.getElementById('bmLight');
  const btnDark = document.getElementById('bmDark');
  const btnSat = document.getElementById('bmSatellite');

  if (btnOsm) btnOsm.addEventListener('click', () => switchBasemap('osm'));
  if (btnDark) btnDark.addEventListener('click', () => switchBasemap('dark'));
  if (btnSat) btnSat.addEventListener('click', () => switchBasemap('satellite'));

  // Map Reset & Clustering
  document.getElementById('resetViewBtn').addEventListener('click', () => {
    if (lastSearchResults.length > 0) {
      fitMapToResults(lastSearchResults);
    } else {
      map.setView([52.5200, 13.4050], 13);
    }
  });

  let clustersActive = true;
  document.getElementById('clusterToggleBtn').addEventListener('click', () => {
    clustersActive = !clustersActive;
    if (clustersActive) {
      map.addLayer(markersClusterGroup);
      showToast('Marker clustering enabled', 'info');
    } else {
      map.removeLayer(markersClusterGroup);
      showToast('Marker clustering disabled', 'info');
    }
  });

  // Tabs Switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      switchTab(btn.getAttribute('data-tab'));
    });
  });

  // Re-run Custom QL Button
  document.getElementById('reRunQlBtn').addEventListener('click', rerunCustomOverpass);

  // Copy QL Button
  document.getElementById('copyQlBtn').addEventListener('click', () => {
    const ql = document.getElementById('overpassEditor').value;
    navigator.clipboard.writeText(ql).then(() => {
      showToast('Overpass QL copied to clipboard', 'success');
    });
  });

  // Clear History
  document.getElementById('clearHistoryBtn').addEventListener('click', async () => {
    await fetch('/api/history', { method: 'DELETE' });
    loadSearchHistory();
    showToast('Search history cleared', 'info');
  });

  // Filter Saved Spots
  document.getElementById('savedStatusFilter').addEventListener('change', (e) => {
    loadSavedSpots(e.target.value);
  });

  // Live Benchmark Button
  document.getElementById('runLiveEvalBtn').addEventListener('click', runLiveBenchmark);

  // Save Spot Modal Actions
  document.getElementById('closeSaveModalBtn').addEventListener('click', closeSaveModal);
  document.getElementById('cancelSaveBtn').addEventListener('click', closeSaveModal);
  document.getElementById('confirmSaveBtn').addEventListener('click', submitSaveSpot);

  // Mobile Toggle Panel
  const togglePanelBtn = document.getElementById('togglePanelBtn');
  const sidePanel = document.getElementById('sidePanel');
  if (togglePanelBtn) {
    togglePanelBtn.addEventListener('click', () => {
      sidePanel.classList.toggle('hidden');
    });
  }
}

// --- Basemap Switcher ---
function switchBasemap(type) {
  const target = (type === 'light') ? 'osm' : type;
  if (currentBasemap === target) return;

  if (TILE_LAYERS[currentBasemap]) {
    map.removeLayer(TILE_LAYERS[currentBasemap]);
  }
  if (TILE_LAYERS[target]) {
    map.addLayer(TILE_LAYERS[target]);
  }
  currentBasemap = target;

  const mapEl = document.getElementById('map');
  if (mapEl) {
    if (target === 'dark') {
      mapEl.classList.add('dark-mode-map');
    } else {
      mapEl.classList.remove('dark-mode-map');
    }
  }

  const btnDark = document.getElementById('bmDark');
  const btnOsm = document.getElementById('bmOSM') || document.getElementById('bmLight');
  const btnSat = document.getElementById('bmSatellite');

  [btnOsm, btnDark, btnSat].forEach(b => {
    if (b) b.className = 'px-2.5 py-1 text-xs rounded-lg font-medium text-slate-400 hover:text-white hover:bg-white/5 transition';
  });

  if ((target === 'osm' || target === 'light') && btnOsm) {
    btnOsm.className = 'px-2.5 py-1 text-xs rounded-lg font-medium bg-brand-600 text-white transition';
  }
  if (target === 'dark' && btnDark) {
    btnDark.className = 'px-2.5 py-1 text-xs rounded-lg font-medium bg-brand-600 text-white transition';
  }
  if (target === 'satellite' && btnSat) {
    btnSat.className = 'px-2.5 py-1 text-xs rounded-lg font-medium bg-brand-600 text-white transition';
  }
}

// --- Tab Switching ---
function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    if (btn.getAttribute('data-tab') === tabName) {
      btn.className = 'tab-btn flex-1 py-2.5 text-center text-brand-400 border-b-2 border-brand-500 transition flex items-center justify-center space-x-1';
    } else {
      btn.className = 'tab-btn flex-1 py-2.5 text-center text-slate-400 hover:text-slate-200 transition flex items-center justify-center space-x-1';
    }
  });

  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.add('hidden');
  });

  const activeContent = document.getElementById(`tabContent${capitalize(tabName)}`);
  if (activeContent) {
    activeContent.classList.remove('hidden');
  }

  if (tabName === 'history') loadSearchHistory();
  if (tabName === 'saved') loadSavedSpots();
  if (tabName === 'eval') loadMetricsData();
}

// --- Search Pipeline Execution ---
async function performSearch(queryText, timeOverride = null) {
  switchTab('results');
  startProgressStepper();

  // Reset UI elements
  document.getElementById('emptyResultsState').classList.add('hidden');
  document.getElementById('resultsSkeleton').classList.remove('hidden');
  document.getElementById('placesContainer').innerHTML = '';
  document.getElementById('relaxBanner').classList.add('hidden');
  document.getElementById('resultsMeta').classList.add('hidden');

  const itinContainer = document.getElementById('itineraryCardContainer');
  if (itinContainer) itinContainer.classList.add('hidden');
  const timeReachBanner = document.getElementById('timeReachBanner');
  if (timeReachBanner) timeReachBanner.classList.add('hidden');

  markersClusterGroup.clearLayers();
  relationLinesGroup.clearLayers();
  if (isochroneLayerGroup) isochroneLayerGroup.clearLayers();
  if (itineraryRouteLayerGroup) itineraryRouteLayerGroup.clearLayers();

  const forceBaseline = document.getElementById('forceBaselineToggle').checked;

  try {
    const payload = { query: queryText, force_baseline: forceBaseline };
    if (timeOverride !== null) {
      payload.time_min_override = timeOverride;
    }

    const resp = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await resp.json();
    stopProgressStepper();
    document.getElementById('resultsSkeleton').classList.add('hidden');

    if (!resp.ok) {
      throw new Error(data.detail || 'Search request failed.');
    }

    handleSearchSuccess(data);
  } catch (err) {
    stopProgressStepper();
    document.getElementById('resultsSkeleton').classList.add('hidden');
    document.getElementById('emptyResultsState').classList.remove('hidden');
    showToast(err.message, 'error');
  }
}

function handleSearchSuccess(data) {
  lastSearchData = data;
  lastSearchQueryObj = data.parsed_query;

  // Language Badge (English Only)
  const langContainer = document.getElementById('langBadgeContainer');
  const langBadge = document.getElementById('langBadge');
  if (langContainer && langBadge) {
    langContainer.classList.remove('hidden');
    langBadge.textContent = 'EN';
  }

  // Relaxation Banner
  if (data.relaxation_applied) {
    const relaxBanner = document.getElementById('relaxBanner');
    const relaxMsg = document.getElementById('relaxMessage');
    relaxMsg.textContent = data.relaxation_applied;
    relaxBanner.classList.remove('hidden');
  }

  // Meta stats
  document.getElementById('resultsMeta').classList.remove('hidden');
  document.getElementById('latencyText').textContent = `${data.total_latency_ms} ms (${data.method_used})`;
  const countBadge = document.getElementById('resultsCountBadge');

  // Populate Explain Tab
  document.getElementById('jsonViewer').textContent = JSON.stringify(data.parsed_query, null, 2);
  document.getElementById('explainMethodBadge').textContent = data.method_used;
  if (document.getElementById('overpassEditor')) {
    document.getElementById('overpassEditor').value = data.overpass_ql || '// Natural language processing & routing handled via pipeline';
  }

  const explainRoutingBadge = document.getElementById('explainRoutingSourceBadge');
  const explainRoutingDesc = document.getElementById('explainRoutingDesc');
  const explainPolygonStatus = document.getElementById('explainPolygonStatus');
  const explainPolygonSnippet = document.getElementById('explainPolygonSnippet');
  if (explainRoutingBadge) {
    explainRoutingBadge.textContent = data.routing_source || (data.itinerary ? data.itinerary.routing_source : 'OSRM foot');
  }

  // Mapped Tags Container
  const mappedContainer = document.getElementById('mappedTagsContainer');
  mappedContainer.innerHTML = '';
  if (data.parsed_query.entities) {
    data.parsed_query.entities.forEach(ent => {
      (ent.tags || []).forEach(tag => {
        const pill = document.createElement('a');
        pill.href = `https://taginfo.openstreetmap.org/tags/${encodeURIComponent(tag.replace('=', '/'))}`;
        pill.target = '_blank';
        pill.className = 'px-2 py-1 rounded bg-brand-500/10 hover:bg-brand-500/20 text-brand-300 font-mono text-[11px] border border-brand-500/30 flex items-center space-x-1';
        pill.innerHTML = `<span>${ent.name}:</span> <strong class="text-cyan-300">${tag}</strong>`;
        mappedContainer.appendChild(pill);
      });
    });
  } else if (data.parsed_query.itinerary && data.parsed_query.itinerary.stops) {
    data.parsed_query.itinerary.stops.forEach(st => {
      (st.tags || []).forEach(tag => {
        const pill = document.createElement('a');
        pill.href = `https://taginfo.openstreetmap.org/tags/${encodeURIComponent(tag.replace('=', '/'))}`;
        pill.target = '_blank';
        pill.className = 'px-2 py-1 rounded bg-brand-500/10 hover:bg-brand-500/20 text-brand-300 font-mono text-[11px] border border-brand-500/30 flex items-center space-x-1';
        pill.innerHTML = `<span>${st.name}:</span> <strong class="text-cyan-300">${tag}</strong>`;
        mappedContainer.appendChild(pill);
      });
    });
  }

  // CASE 1: ITINERARY QUERY (FEATURE 2)
  if (data.query_type === 'itinerary') {
    const itinCount = (data.itinerary && data.itinerary.itineraries) ? data.itinerary.itineraries.length : 0;
    countBadge.textContent = itinCount;
    countBadge.classList.remove('hidden');
    document.getElementById('resultsFoundText').textContent = `Generated ${itinCount} walking itinerary plan(s) in ${data.parsed_query.area}`;
    
    document.getElementById('placesContainer').innerHTML = '';
    const itinCard = document.getElementById('itineraryCardContainer');
    if (itinCard) itinCard.classList.remove('hidden');

    if (explainPolygonStatus) explainPolygonStatus.textContent = `Beam Planning Matrix (Width=5, OSRM foot)`;
    if (explainRoutingDesc) explainRoutingDesc.innerHTML = `Walking matrix via <code class="text-indigo-300">${data.routing_source}</code> duration table`;
    if (explainPolygonSnippet) explainPolygonSnippet.classList.add('hidden');

    renderItinerary(data.itinerary, 0);
    return;
  }

  // CASE 2: TIME-BASED SEARCH (FEATURE 1)
  if (data.query_type === 'time_based') {
    lastSearchResults = data.results || [];
    countBadge.textContent = data.results_count;
    countBadge.classList.remove('hidden');
    document.getElementById('resultsFoundText').textContent = `Found ${data.results_count} places within ${data.time_min}m walk in ${data.parsed_query.area}`;

    // Sync slider value
    const slider = document.getElementById('walkingSlider');
    const sliderVal = document.getElementById('walkingSliderVal');
    if (slider && data.time_min) {
      slider.value = data.time_min;
      if (sliderVal) sliderVal.textContent = `${data.time_min} min`;
    }

    // Show Time Reach Banner
    const timeBanner = document.getElementById('timeReachBanner');
    if (timeBanner) {
      timeBanner.classList.remove('hidden');
      const titleEl = document.getElementById('timeReachTitle');
      const descEl = document.getElementById('timeReachDesc');
      const badgeEl = document.getElementById('timeReachRoutingSourceBadge');
      if (titleEl) titleEl.textContent = `${data.time_min} Minute Walking Reach Polygon`;
      if (badgeEl) badgeEl.textContent = data.routing_source;
      const anchorNames = (data.anchors || []).map(a => a.name).join(', ') || 'anchor points';
      if (descEl) descEl.textContent = `Walking reach area computed around ${data.anchors ? data.anchors.length : 1} anchor(s): ${anchorNames}. Candidates isolated using Shapely polygon containment.`;
    }

    if (explainPolygonStatus) explainPolygonStatus.textContent = `Active (${data.routing_source} Reach Polygon)`;
    if (explainPolygonSnippet && data.isochrone_geojson) {
      explainPolygonSnippet.classList.remove('hidden');
      explainPolygonSnippet.textContent = JSON.stringify(data.isochrone_geojson, null, 2);
    }

    renderPlacesCards(data.results, true);
    renderTimeBasedMap(data);
    return;
  }

  // CASE 3: STANDARD SPATIAL QUERY
  lastSearchResults = data.results || [];
  countBadge.textContent = data.results_count;
  countBadge.classList.remove('hidden');
  document.getElementById('resultsFoundText').textContent = `Found ${data.results_count} places in ${data.parsed_query.area}`;

  if (explainPolygonStatus) explainPolygonStatus.textContent = `Standard Proximity Buffer`;
  if (explainPolygonSnippet) explainPolygonSnippet.classList.add('hidden');

  renderPlacesCards(data.results, false);
  renderMapMarkers(data.results, data.geocode);
}

// --- Render Itinerary Component (Feature 2) ---
function renderItinerary(itinData, planIndex = 0) {
  currentItineraryData = itinData;
  currentItineraryIndex = planIndex;

  const itineraries = itinData.itineraries || [];
  if (itineraries.length === 0) return;
  const activePlan = itineraries[planIndex] || itineraries[0];

  // Update Option Tabs
  const tabsContainer = document.getElementById('itineraryTabsHeader');
  if (tabsContainer) {
    tabsContainer.querySelectorAll('.itin-tab-btn').forEach((btn, idx) => {
      if (idx === planIndex) {
        btn.className = 'itin-tab-btn px-2.5 py-1 text-xs font-semibold rounded-lg bg-brand-600 text-white transition';
      } else {
        btn.className = 'itin-tab-btn px-2.5 py-1 text-xs font-semibold rounded-lg text-slate-400 hover:text-white transition';
      }
    });
  }

  // Update Summary Stats
  const totalTimeEl = document.getElementById('itinTotalTime');
  const totalDistEl = document.getElementById('itinTotalDist');
  const routingBadgeEl = document.getElementById('itineraryRoutingSourceBadge');
  if (totalTimeEl) totalTimeEl.textContent = `${activePlan.total_walking_time_min} min`;
  if (totalDistEl) totalDistEl.textContent = `${activePlan.total_distance_m} m`;
  if (routingBadgeEl) routingBadgeEl.textContent = activePlan.routing_source || itinData.routing_source || 'OSRM foot';

  // Render Timeline
  const timelineList = document.getElementById('itineraryTimelineList');
  if (timelineList) {
    timelineList.innerHTML = '';
    const stops = activePlan.stops || [];
    const legs = activePlan.legs || [];

    stops.forEach((s, idx) => {
      const stopEl = document.createElement('div');
      stopEl.className = 'p-2.5 rounded-xl bg-dark-950 border border-white/5 space-y-1 hover:border-brand-500/40 transition cursor-pointer';
      stopEl.innerHTML = `
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="w-5 h-5 rounded-full bg-cyan-500/20 text-cyan-300 font-bold text-[10px] flex items-center justify-center border border-cyan-500/40">
              ${s.stop_number || idx + 1}
            </span>
            <span class="font-bold text-white text-xs truncate max-w-[210px]" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</span>
          </div>
          <span class="text-[10px] uppercase font-semibold text-brand-300 px-1.5 py-0.5 rounded bg-brand-600/20">${escapeHtml(s.concept)}</span>
        </div>
        <p class="text-[10px] text-slate-400 pl-7">${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}</p>
      `;
      stopEl.addEventListener('click', () => {
        map.flyTo([s.lat, s.lon], 17);
      });
      timelineList.appendChild(stopEl);

      if (idx < legs.length) {
        const leg = legs[idx];
        const legEl = document.createElement('div');
        legEl.className = 'py-1 px-4 text-[11px] text-cyan-300 flex items-center space-x-2 font-medium';
        legEl.innerHTML = `
          <span class="text-slate-500">&darr;</span>
          <span>🚶 <strong>${leg.duration_min} min walk</strong> (${leg.distance_m} m)</span>
          <span class="text-[9px] text-slate-500 font-mono">via ${leg.source}</span>
        `;
        timelineList.appendChild(legEl);
      }
    });
  }

  // Draw on Map
  itineraryRouteLayerGroup.clearLayers();
  markersClusterGroup.clearLayers();
  relationLinesGroup.clearLayers();
  if (isochroneLayerGroup) isochroneLayerGroup.clearLayers();

  // 1. Draw Route Geometry Line
  if (activePlan.route_geojson && activePlan.route_geojson.geometry) {
    L.geoJSON(activePlan.route_geojson, {
      style: {
        color: '#06b6d4',
        weight: 4,
        opacity: 0.95,
        lineCap: 'round',
        lineJoin: 'round'
      }
    }).addTo(itineraryRouteLayerGroup);
  }

  // 2. Draw Numbered Stop Markers
  const stopLatLngs = [];
  (activePlan.stops || []).forEach((s, idx) => {
    const latLng = [s.lat, s.lon];
    stopLatLngs.push(latLng);

    const pin = L.marker(latLng, {
      icon: createCustomPin('#06b6d4', s.stop_number || idx + 1)
    }).bindPopup(`
      <div style="font-family: 'Inter', sans-serif; color: #0f172a;">
        <span style="font-size: 10px; font-weight: 700; color: #4f46e5; text-transform: uppercase;">Stop ${s.stop_number || idx + 1}: ${escapeHtml(s.concept)}</span>
        <h4 style="font-weight: 700; font-size: 13px; margin: 2px 0 4px 0;">${escapeHtml(s.name)}</h4>
        <p style="font-size: 11px; color: #64748b; margin: 0;">${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}</p>
      </div>
    `);
    itineraryRouteLayerGroup.addLayer(pin);
  });

  if (stopLatLngs.length > 0) {
    const bounds = L.latLngBounds(stopLatLngs);
    map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 });
  }
}

// --- Export Itinerary Functions (Feature 2) ---
async function exportItineraryGeoJSON() {
  if (!currentItineraryData || !currentItineraryData.itineraries || currentItineraryData.itineraries.length === 0) {
    showToast('No active itinerary to export.', 'error');
    return;
  }
  const plan = currentItineraryData.itineraries[currentItineraryIndex] || currentItineraryData.itineraries[0];
  try {
    const resp = await fetch('/api/export/itinerary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ itinerary_data: plan, format: 'geojson' })
    });
    if (!resp.ok) throw new Error('Failed generating GeoJSON export.');
    const blob = await resp.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tracespot_itinerary_plan_${currentItineraryIndex + 1}.geojson`;
    a.click();
    window.URL.revokeObjectURL(url);
    showToast('Exported itinerary as GeoJSON', 'success');
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function exportItineraryText() {
  if (!currentItineraryData || !currentItineraryData.itineraries || currentItineraryData.itineraries.length === 0) {
    showToast('No active itinerary to export.', 'error');
    return;
  }
  const plan = currentItineraryData.itineraries[currentItineraryIndex] || currentItineraryData.itineraries[0];
  try {
    const resp = await fetch('/api/export/itinerary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ itinerary_data: plan, format: 'text' })
    });
    if (!resp.ok) throw new Error('Failed generating text export.');
    const blob = await resp.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tracespot_itinerary_plan_${currentItineraryIndex + 1}.txt`;
    a.click();
    window.URL.revokeObjectURL(url);
    showToast('Exported printable itinerary timeline', 'success');
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// --- Render Map for Time-Based Search (Feature 1) ---
function renderTimeBasedMap(data) {
  markersClusterGroup.clearLayers();
  relationLinesGroup.clearLayers();
  if (isochroneLayerGroup) isochroneLayerGroup.clearLayers();
  if (itineraryRouteLayerGroup) itineraryRouteLayerGroup.clearLayers();

  // 1. Draw Isochrone Reach Polygon
  if (data.isochrone_geojson) {
    L.geoJSON(data.isochrone_geojson, {
      style: function(feature) {
        const contour = (feature.properties && feature.properties.contour) ? feature.properties.contour : (data.time_min || 10);
        let color = '#6366f1';
        if (contour <= 5) color = '#10b981';
        else if (contour <= 10) color = '#06b6d4';
        else color = '#8b5cf6';
        return {
          color: color,
          weight: 2.5,
          opacity: 0.9,
          fillColor: color,
          fillOpacity: 0.22,
          dashArray: '4, 4'
        };
      },
      onEachFeature: function(feature, layer) {
        const contour = (feature.properties && feature.properties.contour) ? feature.properties.contour : data.time_min;
        layer.bindTooltip(`🚶 ${contour} min Walking Reach (${data.routing_source})`, { sticky: true });
      }
    }).addTo(isochroneLayerGroup);
  }

  const allLatLngs = [];

  // 2. Draw Anchor Markers
  if (data.anchors && data.anchors.length > 0) {
    data.anchors.forEach(a => {
      allLatLngs.push([a.lat, a.lon]);
      const anchorPin = L.marker([a.lat, a.lon], {
        icon: createCustomPin('#f59e0b', '⚓')
      }).bindPopup(`
        <div style="font-family: 'Inter', sans-serif; color: #0f172a;">
          <span style="font-size: 10px; font-weight: 700; color: #d97706; text-transform: uppercase;">Anchor Location</span>
          <h4 style="font-weight: 700; font-size: 13px; margin: 2px 0 4px 0;">${escapeHtml(a.name)}</h4>
          <p style="font-size: 11px; color: #64748b; margin: 0;">${escapeHtml(a.type)} &bull; ${a.lat.toFixed(5)}, ${a.lon.toFixed(5)}</p>
        </div>
      `);
      relationLinesGroup.addLayer(anchorPin);
    });
  }

  // 3. Draw Candidate Places Pins
  if (data.results && data.results.length > 0) {
    data.results.forEach((p, idx) => {
      allLatLngs.push([p.lat, p.lon]);
      const pin = L.marker([p.lat, p.lon], {
        icon: createCustomPin('#6366f1', idx + 1)
      });
      const popupHtml = `
        <div style="font-family: 'Inter', sans-serif; color: #0f172a; min-width: 200px;">
          <span style="font-size: 10px; font-weight: 700; color: #4f46e5;">#${idx + 1} &bull; ${escapeHtml(p.primary_type)}</span>
          <h4 style="font-weight: 700; font-size: 13px; margin: 2px 0 4px 0;">${escapeHtml(p.name)}</h4>
          <div style="font-size: 11px; background: #e0e7ff; color: #3730a3; padding: 4px 6px; border-radius: 4px; margin: 0 0 6px 0; font-weight: 600;">
            🚶 ${p.walk_time_min} min walk (${p.walk_distance_m} m) &bull; ${escapeHtml(p.routing_source || data.routing_source)}
          </div>
          <p style="font-size: 10px; color: #475569; margin: 0 0 6px 0;">${escapeHtml(p.why_matched)}</p>
          <div style="font-size: 10px; display: flex; gap: 6px;">
            <a href="${p.verification_links.osm}" target="_blank" style="color: #4f46e5; text-decoration: none; font-weight: 600;">OSM</a>
            <a href="${p.verification_links.street_view}" target="_blank" style="color: #4f46e5; text-decoration: none; font-weight: 600;">StreetView</a>
          </div>
        </div>
      `;
      pin.bindPopup(popupHtml);
      markersClusterGroup.addLayer(pin);

      // Walking relation line from anchor to candidate
      if (p.anchor_name && p.related_matches && p.related_matches.length > 0) {
        p.related_matches.forEach(rel => {
          const polyline = L.polyline(rel.relation_line, {
            color: '#10b981',
            weight: 3,
            opacity: 0.85,
            dashArray: '4, 6',
            className: 'relation-line'
          }).bindTooltip(`🚶 ${p.walk_time_min} min walk to ${escapeHtml(p.anchor_name)}`, { sticky: true });
          relationLinesGroup.addLayer(polyline);
        });
      }
    });
  }

  if (allLatLngs.length > 0) {
    const bounds = L.latLngBounds(allLatLngs);
    map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 });
  } else if (data.geocode) {
    map.flyTo([data.geocode.lat, data.geocode.lon], 13);
  }
}

// --- Render Place Cards ---
function renderPlacesCards(places, isTimeBased = false) {
  const container = document.getElementById('placesContainer');
  container.innerHTML = '';

  if (!places || places.length === 0) {
    document.getElementById('emptyResultsState').classList.remove('hidden');
    return;
  }

  places.forEach((p, idx) => {
    const card = document.createElement('div');
    card.className = 'p-3.5 rounded-xl bg-dark-900/90 border border-white/5 hover:border-brand-500/50 hover:bg-dark-850 transition duration-200 space-y-2 cursor-pointer shadow-md group';
    card.setAttribute('data-id', p.id);

    const scorePct = Math.round(p.score * 100);
    const scoreColor = scorePct >= 80 ? 'bg-emerald-400' : (scorePct >= 60 ? 'bg-indigo-400' : 'bg-amber-400');

    card.innerHTML = `
      <div class="flex items-start justify-between">
        <div class="flex-1 pr-2">
          <div class="flex items-center space-x-1.5">
            <span class="w-5 h-5 rounded-md bg-brand-500/20 text-brand-300 font-bold text-[10px] flex items-center justify-center shrink-0">
              ${idx + 1}
            </span>
            <h4 class="text-xs font-bold text-white group-hover:text-brand-300 transition truncate" title="${escapeHtml(p.name)}">
              ${escapeHtml(p.name)}
            </h4>
          </div>
          <span class="text-[11px] text-slate-400 mt-0.5 block truncate">
            ${escapeHtml(p.primary_type)} &bull; ${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}
          </span>
        </div>
        <div class="text-right shrink-0">
          <span class="text-[11px] font-bold text-slate-200">${scorePct}%</span>
          <div class="w-12 h-1.5 rounded-full bg-slate-800 mt-0.5 overflow-hidden">
            <div class="h-full ${scoreColor}" style="width: ${scorePct}%"></div>
          </div>
        </div>
      </div>

      ${p.walk_time_min !== undefined ? `
        <div class="flex items-center space-x-1.5 text-[11px] text-cyan-300 font-semibold pt-0.5">
          <span class="px-2 py-0.5 rounded-full bg-cyan-500/20 border border-cyan-500/30 flex items-center space-x-1">
            <span>🚶</span>
            <span>${p.walk_time_min} min walk</span>
          </span>
          <span class="text-slate-400">(${p.walk_distance_m} m)</span>
          <span class="text-[9px] px-1.5 py-0.2 rounded bg-slate-800 text-indigo-300 border border-white/5 font-mono">${escapeHtml(p.routing_source || 'OSM')}</span>
        </div>
      ` : ''}

      <!-- Why Matched Explanation -->
      <div class="p-2 rounded-lg bg-dark-950/70 border border-white/5 text-[11px] text-slate-300 flex items-center space-x-1.5">
        <svg class="w-3.5 h-3.5 text-cyan-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
        </svg>
        <span class="truncate">${escapeHtml(p.why_matched)}</span>
      </div>

      <!-- Actions & Verification Links -->
      <div class="flex items-center justify-between pt-1 border-t border-white/5 text-[11px]">
        <div class="flex items-center space-x-2 text-slate-400">
          <a href="${p.verification_links.osm}" target="_blank" class="hover:text-cyan-400 transition" title="OpenStreetMap Link">OSM</a>
          <span>&bull;</span>
          <a href="${p.verification_links.street_view}" target="_blank" class="hover:text-cyan-400 transition" title="Google Street View">StreetView</a>
          <span>&bull;</span>
          <a href="${p.verification_links.mapillary}" target="_blank" class="hover:text-cyan-400 transition" title="Mapillary Imagery">Mapillary</a>
          ${p.verification_links.wikipedia ? `<span>&bull;</span><a href="${p.verification_links.wikipedia}" target="_blank" class="hover:text-indigo-400 transition" title="Wikipedia Article">Wiki</a>` : ''}
        </div>
        <button class="save-spot-btn px-2 py-0.5 rounded bg-brand-500/10 hover:bg-brand-500/20 text-brand-300 font-medium hover:text-white border border-brand-500/30 transition flex items-center space-x-1" data-spot='${JSON.stringify(p).replace(/'/g, "&apos;")}'>
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"></path>
          </svg>
          <span>Save</span>
        </button>
      </div>
    `;

    card.addEventListener('click', (e) => {
      if (e.target.closest('a') || e.target.closest('.save-spot-btn')) return;
      focusPlaceOnMap(p);
    });

    card.querySelector('.save-spot-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      openSaveModal(p);
    });

    container.appendChild(card);
  });
}

// --- Render Map Markers for Standard Proximity ---
function renderMapMarkers(places, geocode) {
  markersClusterGroup.clearLayers();
  relationLinesGroup.clearLayers();
  if (isochroneLayerGroup) isochroneLayerGroup.clearLayers();
  if (itineraryRouteLayerGroup) itineraryRouteLayerGroup.clearLayers();

  if (!places || places.length === 0) {
    if (geocode) {
      map.flyTo([geocode.lat, geocode.lon], 13);
    }
    return;
  }

  places.forEach((p, idx) => {
    const marker = L.marker([p.lat, p.lon], {
      icon: createCustomPin('#6366f1', idx + 1)
    });

    const popupHtml = `
      <div style="font-family: 'Inter', sans-serif; color: #0f172a; min-width: 200px;">
        <h4 style="font-weight: 700; font-size: 13px; margin: 0 0 4px 0;">${escapeHtml(p.name)}</h4>
        <p style="font-size: 11px; color: #475569; margin: 0 0 6px 0;"><strong>Type:</strong> ${escapeHtml(p.primary_type)}</p>
        <p style="font-size: 11px; background: #f1f5f9; padding: 4px 6px; border-radius: 4px; margin: 0 0 6px 0;">${escapeHtml(p.why_matched)}</p>
        <div style="font-size: 10px; display: flex; gap: 6px;">
          <a href="${p.verification_links.osm}" target="_blank" style="color: #4f46e5; text-decoration: none; font-weight: 600;">OSM</a>
          <a href="${p.verification_links.street_view}" target="_blank" style="color: #4f46e5; text-decoration: none; font-weight: 600;">StreetView</a>
        </div>
      </div>
    `;
    marker.bindPopup(popupHtml);
    markersClusterGroup.addLayer(marker);

    if (p.related_matches && p.related_matches.length > 0) {
      p.related_matches.forEach(rel => {
        const polyline = L.polyline(rel.relation_line, {
          color: '#06b6d4',
          weight: 2.5,
          opacity: 0.85,
          dashArray: '6, 8',
          className: 'relation-line'
        }).bindTooltip(`${rel.distance_m} m to ${escapeHtml(rel.name)}`, { sticky: true });

        relationLinesGroup.addLayer(polyline);

        const contextMarker = L.marker([rel.lat, rel.lon], {
          icon: createCustomPin('#06b6d4', '')
        }).bindPopup(`
          <div style="font-family: 'Inter', sans-serif; color: #0f172a;">
            <h4 style="font-weight: 700; font-size: 12px; margin: 0;">${escapeHtml(rel.name)}</h4>
            <p style="font-size: 11px; color: #475569; margin: 2px 0 0 0;">(${escapeHtml(rel.type)})</p>
          </div>
        `);
        relationLinesGroup.addLayer(contextMarker);
      });
    }
  });

  fitMapToResults(places);
}

function focusPlaceOnMap(place) {
  map.flyTo([place.lat, place.lon], 17, { duration: 1.2 });
}

function fitMapToResults(places) {
  if (!places || places.length === 0) return;
  const bounds = L.latLngBounds(places.map(p => [p.lat, p.lon]));
  map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 });
}

// --- Re-Run Custom Overpass QL ---
async function rerunCustomOverpass() {
  const ql = document.getElementById('overpassEditor').value.trim();
  if (!ql) return;

  switchTab('results');
  startProgressStepper();

  try {
    const resp = await fetch('/api/search/custom-overpass', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ql_query: ql, query_obj: lastSearchQueryObj || { area: 'Berlin', entities: [{ id: 1, name: 'place', tags: ['amenity=cafe'] }] } })
    });
    const data = await resp.json();
    stopProgressStepper();

    if (!resp.ok) throw new Error(data.detail || 'Failed executing custom Overpass QL.');

    lastSearchResults = data.results || [];
    renderPlacesCards(data.results);
    renderMapMarkers(data.results, null);
    showToast(`Executed custom Overpass QL: found ${data.results_count} places`, 'success');
  } catch (e) {
    stopProgressStepper();
    showToast(e.message, 'error');
  }
}

// --- Search History ---
async function loadSearchHistory() {
  const historyList = document.getElementById('historyList');
  historyList.innerHTML = '<div class="text-xs text-slate-500 py-4 text-center">Loading search history...</div>';

  try {
    const resp = await fetch('/api/history?limit=25');
    const items = await resp.json();

    if (!items || items.length === 0) {
      historyList.innerHTML = '<div class="text-xs text-slate-500 py-6 text-center">No search history recorded yet.</div>';
      return;
    }

    historyList.innerHTML = '';
    items.forEach(it => {
      const el = document.createElement('div');
      el.className = 'p-2.5 rounded-xl bg-dark-900 border border-white/5 hover:border-brand-500/40 hover:bg-dark-850 cursor-pointer transition flex items-center justify-between text-xs';
      el.innerHTML = `
        <div class="truncate pr-2">
          <p class="font-semibold text-slate-200 truncate">${escapeHtml(it.query_text)}</p>
          <span class="text-[10px] text-slate-500">${it.timestamp} &bull; ${it.result_count} results &bull; Lang: ${it.detected_lang.toUpperCase()}</span>
        </div>
        <button class="px-2 py-1 rounded bg-white/5 hover:bg-brand-600/30 text-brand-300 font-mono text-[10px] shrink-0">Re-run</button>
      `;
      el.addEventListener('click', () => {
        document.getElementById('queryInput').value = it.query_text;
        performSearch(it.query_text);
      });
      historyList.appendChild(el);
    });
  } catch (err) {
    historyList.innerHTML = '<div class="text-xs text-rose-400 py-4 text-center">Failed loading history.</div>';
  }
}

// --- Saved Spots Board ---
let pendingSpotToSave = null;

function openSaveModal(spot) {
  pendingSpotToSave = spot;
  document.getElementById('saveSpotName').value = spot.name;
  document.getElementById('saveSpotStatus').value = 'Confirmed';
  document.getElementById('saveSpotNote').value = spot.why_matched || '';
  document.getElementById('saveModal').classList.remove('hidden');
}

function closeSaveModal() {
  document.getElementById('saveModal').classList.add('hidden');
  pendingSpotToSave = null;
}

async function submitSaveSpot() {
  if (!pendingSpotToSave) return;

  const payload = {
    spot_name: document.getElementById('saveSpotName').value.trim() || pendingSpotToSave.name,
    lat: pendingSpotToSave.lat,
    lon: pendingSpotToSave.lon,
    tags: pendingSpotToSave.tags || {},
    query_text: document.getElementById('queryInput').value.trim() || 'Direct Spot Save',
    status: document.getElementById('saveSpotStatus').value,
    note: document.getElementById('saveSpotNote').value.trim(),
    osm_id: pendingSpotToSave.osm_id || '',
    osm_type: pendingSpotToSave.osm_type || 'node'
  };

  try {
    const resp = await fetch('/api/saved', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) throw new Error('Failed to save spot.');

    closeSaveModal();
    showToast(`Saved spot "${payload.spot_name}" to board!`, 'success');
    loadSavedSpots();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function loadSavedSpots(statusFilter = 'ALL') {
  const savedList = document.getElementById('savedList');
  savedList.innerHTML = '<div class="text-xs text-slate-500 py-4 text-center">Loading saved spots...</div>';

  try {
    const resp = await fetch('/api/saved');
    let items = await resp.json();

    if (statusFilter && statusFilter !== 'ALL') {
      items = items.filter(it => it.status === statusFilter);
    }

    const badge = document.getElementById('savedCountBadge');
    badge.textContent = items.length;
    badge.classList.remove('hidden');

    if (!items || items.length === 0) {
      savedList.innerHTML = '<div class="text-xs text-slate-500 py-6 text-center">No saved spots found.</div>';
      return;
    }

    savedList.innerHTML = '';
    items.forEach(it => {
      const card = document.createElement('div');
      card.className = 'p-3 rounded-xl bg-dark-900 border border-white/5 space-y-2 text-xs';

      const statusBadgeClass = it.status === 'Confirmed'
        ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
        : (it.status === 'Likely' ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' : 'bg-rose-500/20 text-rose-300 border-rose-500/30');

      card.innerHTML = `
        <div class="flex items-start justify-between">
          <div class="truncate pr-2">
            <h4 class="font-bold text-white text-xs truncate">${escapeHtml(it.spot_name)}</h4>
            <span class="text-[10px] text-slate-500">${it.lat.toFixed(5)}, ${it.lon.toFixed(5)} &bull; Query: "${escapeHtml(it.query_text)}"</span>
          </div>
          <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${statusBadgeClass}">${it.status}</span>
        </div>

        ${it.note ? `<p class="p-2 rounded bg-dark-950/70 border border-white/5 text-[11px] text-slate-300">${escapeHtml(it.note)}</p>` : ''}

        <div class="flex items-center justify-between pt-1 border-t border-white/5 text-[11px]">
          <button class="fly-to-saved-btn text-cyan-400 hover:underline">Show on Map</button>
          <div class="flex items-center space-x-2">
            <select class="status-select bg-dark-950 border border-white/10 rounded px-1.5 py-0.5 text-[10px] text-slate-300 outline-none">
              <option value="Confirmed" ${it.status === 'Confirmed' ? 'selected' : ''}>Confirmed</option>
              <option value="Likely" ${it.status === 'Likely' ? 'selected' : ''}>Likely</option>
              <option value="Rejected" ${it.status === 'Rejected' ? 'selected' : ''}>Rejected</option>
            </select>
            <button class="delete-saved-btn text-rose-400 hover:text-rose-300 font-bold px-1">&times;</button>
          </div>
        </div>
      `;

      card.querySelector('.fly-to-saved-btn').addEventListener('click', () => {
        map.flyTo([it.lat, it.lon], 17);
        showToast(`Centered on ${it.spot_name}`, 'info');
      });

      card.querySelector('.status-select').addEventListener('change', async (e) => {
        await fetch(`/api/saved/${it.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: e.target.value })
        });
        loadSavedSpots(document.getElementById('savedStatusFilter').value);
      });

      card.querySelector('.delete-saved-btn').addEventListener('click', async () => {
        await fetch(`/api/saved/${it.id}`, { method: 'DELETE' });
        loadSavedSpots(document.getElementById('savedStatusFilter').value);
        showToast('Spot deleted', 'info');
      });

      savedList.appendChild(card);
    });
  } catch (e) {
    savedList.innerHTML = '<div class="text-xs text-rose-400 py-4 text-center">Failed loading saved spots.</div>';
  }
}

// --- Metrics & 4-Pillar Ablation Data ---
async function loadMetricsData() {
  try {
    const resp = await fetch('/api/ablation');
    const data = await resp.json();
    if (data.error) return;

    if (data.parser_accuracy) {
      const timeAcc = data.parser_accuracy.time_based;
      const itinAcc = data.parser_accuracy.itinerary;
      const geom = data.geometry_check;
      const itinCheck = data.itinerary_check;

      const timeEl = document.getElementById('metricTimeExact');
      if (timeEl) timeEl.textContent = `${timeAcc.exact_match_pct}%`;

      const itinEl = document.getElementById('metricItinExact');
      if (itinEl) itinEl.textContent = `${itinAcc.exact_match_pct}%`;

      const geomEl = document.getElementById('metricGeomVerified');
      if (geomEl) geomEl.textContent = `${geom.pct_correct}%`;

      const beamEl = document.getElementById('metricBeamImprove');
      if (beamEl) beamEl.textContent = `+${itinCheck.improvement_pct}%`;
    }

    if (data.ablation_table) {
      renderAblationTable(data.ablation_table);
      renderAblationChart(data.ablation_table);
    }
  } catch (err) {
    console.error('Failed loading ablation metrics', err);
  }
}

function renderAblationTable(tableRows) {
  const tbody = document.getElementById('ablationTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';

  tableRows.forEach((r, idx) => {
    const tr = document.createElement('tr');
    const isFull = idx === 0;
    tr.className = `border-b border-white/5 ${isFull ? 'bg-brand-500/10 text-white font-semibold' : 'text-slate-300'}`;
    tr.innerHTML = `
      <td class="py-1 pr-2 ${isFull ? 'text-brand-300 font-bold' : ''}">${escapeHtml(r.configuration)}</td>
      <td class="py-1 px-1 text-right text-emerald-400 font-bold">${r.exact_match_pct.toFixed(1)}%</td>
      <td class="py-1 px-1 text-right text-cyan-300">${r.tag_accuracy_pct.toFixed(1)}%</td>
      <td class="py-1 px-1 text-right ${r.hallucinated_tag_rate_pct > 0 ? 'text-rose-400' : 'text-emerald-400'}">${r.hallucinated_tag_rate_pct.toFixed(1)}%</td>
      <td class="py-1 px-1 text-right ${r.invalid_json_rate_pct > 0 ? 'text-rose-400' : 'text-emerald-400'}">${r.invalid_json_rate_pct.toFixed(1)}%</td>
      <td class="py-1 pl-1 text-right text-amber-300">${r.latency_ms.toFixed(1)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderAblationChart(tableRows) {
  const chartEl = document.getElementById('evalChart');
  if (!chartEl) return;
  const ctx = chartEl.getContext('2d');
  if (evalChartInstance) evalChartInstance.destroy();

  const labels = tableRows.map(r => r.configuration.split('(')[0].trim());
  const exactMatches = tableRows.map(r => r.exact_match_pct);
  const tagAccs = tableRows.map(r => r.tag_accuracy_pct);

  evalChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Exact Match (%)',
          data: exactMatches,
          backgroundColor: 'rgba(99, 102, 241, 0.8)',
          borderColor: 'rgba(99, 102, 241, 1)',
          borderWidth: 1,
          borderRadius: 4
        },
        {
          label: 'Tag Accuracy (%)',
          data: tagAccs,
          backgroundColor: 'rgba(6, 182, 212, 0.7)',
          borderColor: 'rgba(6, 182, 212, 1)',
          borderWidth: 1,
          borderRadius: 4
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          min: 60,
          max: 100,
          ticks: { color: '#94a3b8', font: { family: 'Inter', size: 10 } },
          grid: { color: 'rgba(255,255,255,0.05)' }
        },
        x: {
          ticks: { color: '#94a3b8', font: { family: 'Inter', size: 10 } },
          grid: { display: false }
        }
      },
      plugins: {
        legend: {
          labels: { color: '#cbd5e1', font: { family: 'Inter', size: 10 }, boxWidth: 12 }
        }
      }
    }
  });
}

// --- Live Benchmark Execution ---
async function runLiveBenchmark() {
  const btn = document.getElementById('runLiveEvalBtn');
  const tableContainer = document.getElementById('liveEvalResults');
  const table = document.getElementById('liveEvalTable');

  btn.disabled = true;
  btn.innerHTML = 'Testing...';
  tableContainer.classList.remove('hidden');
  table.innerHTML = '<div class="text-slate-400 py-2">Running live inference comparison on 10 queries...</div>';

  try {
    const resp = await fetch('/api/evaluate/live', { method: 'POST' });
    const data = await resp.json();
    btn.disabled = false;
    btn.innerHTML = 'Run Live Test';

    table.innerHTML = '';
    data.comparisons.forEach(c => {
      const row = document.createElement('div');
      row.className = 'p-2 rounded bg-dark-950 border border-white/5 space-y-1';
      row.innerHTML = `
        <div class="text-white font-semibold">${escapeHtml(c.query)}</div>
        <div class="flex justify-between text-slate-400 text-[9px]">
          <span>Baseline: <strong class="text-amber-400">${c.baseline.latency_ms} ms</strong></span>
          <span>Model: <strong class="text-indigo-400">${c.model.latency_ms} ms</strong> (${c.model.method})</span>
        </div>
      `;
      table.appendChild(row);
    });
    showToast('Live benchmark completed!', 'success');
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = 'Run Live Test';
    showToast(err.message, 'error');
  }
}

// --- Progress Stepper Animation ---
function startProgressStepper() {
  const stepper = document.getElementById('progressStepper');
  const timer = document.getElementById('stepTimer');
  stepper.classList.remove('hidden');

  let seconds = 0;
  timer.textContent = '0.0s';
  clearInterval(progressInterval);
  progressInterval = setInterval(() => {
    seconds += 0.1;
    timer.textContent = `${seconds.toFixed(1)}s`;
  }, 100);

  const s1 = document.getElementById('step1');
  const s2 = document.getElementById('step2');
  const s3 = document.getElementById('step3');
  const s4 = document.getElementById('step4');

  [s1, s2, s3, s4].forEach(s => s.className = 'py-1 rounded bg-slate-800 text-slate-400 transition');

  s1.className = 'py-1 rounded bg-brand-600 text-white font-bold animate-pulse';
  setTimeout(() => {
    s1.className = 'py-1 rounded bg-emerald-600/50 text-white';
    s2.className = 'py-1 rounded bg-brand-600 text-white font-bold animate-pulse';
  }, 300);

  setTimeout(() => {
    s2.className = 'py-1 rounded bg-emerald-600/50 text-white';
    s3.className = 'py-1 rounded bg-brand-600 text-white font-bold animate-pulse';
  }, 700);

  setTimeout(() => {
    s3.className = 'py-1 rounded bg-emerald-600/50 text-white';
    s4.className = 'py-1 rounded bg-brand-600 text-white font-bold animate-pulse';
  }, 1400);
}

function stopProgressStepper() {
  clearInterval(progressInterval);
  const s4 = document.getElementById('step4');
  if (s4) s4.className = 'py-1 rounded bg-emerald-600 text-white font-bold';
  setTimeout(() => {
    const stepper = document.getElementById('progressStepper');
    if (stepper) stepper.classList.add('hidden');
  }, 1200);
}

// --- Toast Notifications ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  const colors = {
    info: 'bg-dark-900 border-indigo-500/40 text-indigo-200',
    success: 'bg-dark-900 border-emerald-500/40 text-emerald-200',
    error: 'bg-dark-900 border-rose-500/40 text-rose-200'
  };

  toast.className = `p-3 rounded-xl border shadow-xl text-xs flex items-center space-x-2 transition-all transform duration-300 pointer-events-auto ${colors[type] || colors.info}`;
  toast.innerHTML = `
    <span class="w-2 h-2 rounded-full ${type === 'success' ? 'bg-emerald-400' : (type === 'error' ? 'bg-rose-400' : 'bg-indigo-400')}"></span>
    <span class="font-medium">${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// --- Utility Helpers ---
function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function capitalize(s) {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1);
}
