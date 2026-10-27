// Bronx Mobile Care Broker — Frontend Application Logic (Healthcare Persona UI)

let currentSchedule = null;
let allSchedules = [];
let selectedFlyerSatIndex = 1;
let mapInstance = null;
let googleMapInstance = null;
let googleInfoWindow = null;
let isGoogleMaps = false;
let mapGeoData = null;
let googleMapLayers = {
  stops: [],
  clinics: [],
  tracts: [],
  outliers: [],
};
let mapLayerGroups = {
  stops: null,
  clinics: null,
  tracts: null,
  outliers: null,
};
let activeReplanStopId = null;

// Toast Notification Helper (Replaces blocking browser alerts)
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  const bgClass =
    type === 'error'
      ? 'bg-red-700 text-white border-red-800'
      : type === 'info'
      ? 'bg-slate-800 text-white border-slate-700'
      : 'bg-emerald-700 text-white border-emerald-800';

  toast.className = `${bgClass} border px-4 py-3 rounded-xl shadow-lg flex items-center gap-3 text-sm font-medium transition-all duration-300`;
  toast.innerHTML = `
    <i class="fa-solid ${
      type === 'error' ? 'fa-circle-exclamation' : 'fa-circle-check'
    }"></i>
    <span>${message}</span>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// Tab Switching
function switchTab(tabId) {
  document.querySelectorAll('.tab-content').forEach((el) => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.classList.remove('border-emerald-500', 'text-emerald-700', 'bg-emerald-50/60');
    btn.classList.add('border-transparent', 'text-slate-600');
  });

  const normalized = tabId.replace('-tab', '');
  const target = document.getElementById('tab-' + tabId) || document.getElementById('tab-' + normalized + '-tab');
  if (target) target.classList.add('active');

  const activeBtn = document.getElementById('nav-' + tabId) || document.getElementById('nav-' + normalized + '-tab');
  if (activeBtn) {
    activeBtn.classList.remove('border-transparent', 'text-slate-600');
    activeBtn.classList.add('border-emerald-500', 'text-emerald-700', 'bg-emerald-50/60');
  }

  if (tabId === 'map-tab' || tabId === 'map' || normalized === 'map') {
    setTimeout(initOrRefreshMap, 60);
    setTimeout(() => {
      if (isGoogleMaps && googleMapInstance && window.google && window.google.maps) {
        google.maps.event.trigger(googleMapInstance, 'resize');
      } else if (mapInstance && typeof mapInstance.invalidateSize === 'function') {
        mapInstance.invalidateSize();
      }
    }, 180);
  }
}

// Toggle AI Care Copilot Drawer
function toggleCopilotDrawer() {
  const drawer = document.getElementById('copilot-drawer');
  if (!drawer) return;
  drawer.classList.toggle('hidden');
}

// Load All Schedules for the Schedule History Switcher
async function loadScheduleHistory() {
  try {
    const res = await fetch('/api/schedules');
    if (!res.ok) return;
    allSchedules = await res.json();
    const select = document.getElementById('schedule-switcher');
    if (!select) return;

    select.innerHTML = allSchedules
      .map((s, idx) => {
        const badge = idx === 0 ? '• Current Plan' : `• ${s.status}`;
        return `<option value="${s.id}" ${
          currentSchedule && currentSchedule.id === s.id ? 'selected' : ''
        }>${s.target_month} (${badge})</option>`;
      })
      .join('');
  } catch (err) {
    console.error('Failed to load schedule history:', err);
  }
}

// Handle Schedule Switcher Change
async function onSwitchSchedule(scheduleId) {
  if (!scheduleId) return;
  try {
    showToast('Loading selected deployment plan...', 'info');
    const res = await fetch(`/api/schedule/${scheduleId}`);
    if (!res.ok) throw new Error('Schedule not found');
    currentSchedule = await res.json();
    renderAllViews();
  } catch (err) {
    showToast('Could not load schedule: ' + err.message, 'error');
  }
}

// Initial Data Load
async function loadInitialSchedule() {
  try {
    const res = await fetch('/api/schedule/current');
    if (res.ok) {
      currentSchedule = await res.json();
    }
    await loadScheduleHistory();
    if (currentSchedule) {
      renderAllViews();
    }
  } catch (err) {
    console.error('Error loading initial schedule:', err);
  }
}

function renderAllViews() {
  if (!currentSchedule) return;
  renderKpiSummary();
  renderSaturdayCards();
  renderFlyerStudio();
  renderGovernanceAudit();
  if (isGoogleMaps && googleMapInstance) {
    plotGoogleMapMarkers();
  } else if (mapInstance) {
    plotMapMarkers();
  }
}

// Render Top Clinical Impact KPI Bar
function renderKpiSummary() {
  const stops = currentSchedule.stops || [];
  const totalPop = stops.reduce((acc, s) => acc + (s.total_pop || 0), 0);
  const avgAsthma =
    stops.length > 0
      ? (stops.reduce((acc, s) => acc + (s.pct_asthma || 0), 0) / stops.length).toFixed(1)
      : '0.0';
  const avgUninsured =
    stops.length > 0
      ? (stops.reduce((acc, s) => acc + (s.pct_uninsured || 0), 0) / stops.length).toFixed(1)
      : '0.0';

  document.getElementById('kpi-month-title').textContent = currentSchedule.target_month || 'Active Deployment';
  document.getElementById('kpi-total-pop').textContent = totalPop.toLocaleString() + ' Residents';
  document.getElementById('kpi-asthma').textContent = `${avgAsthma}% Asthma • ${avgUninsured}% Uninsured`;

  const statusEl = document.getElementById('kpi-plan-status');
  const st = (currentSchedule.status || 'AUDITED').toUpperCase();
  statusEl.textContent = st === 'APPROVED' ? 'Approved for Dispatch' : st === 'REJECTED' ? 'Revision Requested' : 'Equity Verified • Ready';
  statusEl.className =
    st === 'APPROVED'
      ? 'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-300'
      : st === 'REJECTED'
      ? 'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-red-100 text-red-800 border border-red-300'
      : 'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-teal-100 text-teal-800 border border-teal-300';
}

// Render Tab 1: 4-Saturday Deployment Cards
function renderSaturdayCards() {
  const grid = document.getElementById('stops-grid');
  if (!grid) return;
  const stops = currentSchedule.stops || [];

  grid.innerHTML = stops
    .map((stop) => {
      const subways = (stop.subway_lines || [])
        .map(
          (line) =>
            `<span class="inline-flex items-center justify-center px-2 py-0.5 rounded bg-slate-800 text-white font-bold text-xs">${line}</span>`
        )
        .join(' ');
      const buses = (stop.bus_lines || [])
        .map(
          (bus) =>
            `<span class="inline-flex items-center px-2 py-0.5 rounded bg-sky-100 text-sky-900 font-semibold text-xs border border-sky-200">${bus}</span>`
        )
        .join(' ');

      const wf = stop.weather_forecast || {};
      const tempStr = wf.forecast_temp_f ? `${wf.forecast_temp_f}°F` : '54°F';
      const aqiStr = wf.aqi_pm25 ? `AQI ${wf.aqi_pm25}` : 'Good Air';
      const rainStr = wf.precipitation_risk || 'Low Rain Risk';

      // Fix Stock Display: Handle Array of Kit Objects vs Object Dict
      const kits = stop.clinical_kits || [];
      let kitsHtml = '';
      if (Array.isArray(kits)) {
        kitsHtml = kits
          .map((item) => {
            const name = item.kit_name || item.kit_code || 'Clinical Kit';
            const qty = item.quantity != null ? `${item.quantity} units` : '';
            const reason = item.trigger_reason || '';
            return `<div class="bg-slate-50 hover:bg-emerald-50/50 transition rounded-lg p-2 border border-slate-200 text-xs flex flex-col justify-between" title="${reason}">
              <div class="flex items-start justify-between gap-1.5">
                <span class="text-slate-800 font-semibold leading-tight">${name}</span>
                ${qty ? `<span class="font-bold text-emerald-800 bg-emerald-100/90 border border-emerald-300 px-1.5 py-0.5 rounded text-[11px] whitespace-nowrap">${qty}</span>` : ''}
              </div>
              ${reason ? `<div class="text-[10px] text-slate-500 mt-1 line-clamp-1 italic">${reason}</div>` : ''}
            </div>`;
          })
          .join('');
      } else if (typeof kits === 'object' && kits !== null) {
        kitsHtml = Object.entries(kits)
          .map(([k, v]) => {
            const label = k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
            const valStr = typeof v === 'object' && v !== null
              ? (v.quantity != null ? `${v.quantity} units` : v.kit_name || JSON.stringify(v))
              : String(v);
            return `<div class="bg-slate-50 rounded-lg px-2.5 py-1.5 border border-slate-200 flex justify-between items-center text-xs">
              <span class="text-slate-700 font-medium">${label}</span>
              <span class="font-bold text-emerald-700 ml-2">${valStr}</span>
            </div>`;
          })
          .join('');
      }

      const gmapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(stop.street_intersection || (stop.lat + ',' + stop.lon))}`;

      return `
      <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden flex flex-col justify-between hover:shadow-md transition">
        <div>
          <!-- Card Top Banner -->
          <div class="bg-slate-900 text-white px-5 py-3.5 flex justify-between items-center">
            <div class="flex items-center gap-2.5">
              <span class="bg-emerald-500 text-slate-950 font-extrabold text-xs px-2.5 py-1 rounded-md uppercase">
                Saturday ${stop.saturday_index}
              </span>
              <span class="text-sm font-semibold text-slate-200">${stop.saturday_date}</span>
            </div>
            <span class="text-xs bg-slate-800 text-emerald-300 border border-slate-700 px-2.5 py-1 rounded-full font-medium">
              Zone: ${stop.hpsa_name}
            </span>
          </div>

          <div class="p-5 space-y-4">
            <!-- Neighborhood & Landmark -->
            <div>
              <h3 class="text-lg font-bold text-slate-900">${stop.neighborhood}</h3>
              <p class="text-sm font-semibold text-emerald-800 mt-0.5 flex items-start gap-1.5">
                <i class="fa-solid fa-location-dot text-emerald-600 mt-1"></i>
                <span>${stop.landmark_name}</span>
              </p>
              <p class="text-xs text-slate-500 ml-5 mt-0.5">${stop.street_intersection} • 9:00 AM – 3:00 PM</p>
            </div>

            <!-- "A Reason You Can Say Out Loud" -->
            <div class="bg-emerald-50/80 border border-emerald-200 rounded-xl p-3.5">
              <div class="text-xs font-bold uppercase tracking-wider text-emerald-800 flex items-center gap-1.5 mb-1">
                <i class="fa-solid fa-comment-medical"></i> Why This Location ("A Reason You Can Say Out Loud")
              </div>
              <p class="text-xs text-slate-700 leading-relaxed">${stop.siting_rationale || 'High chronic disease burden and zero Saturday primary care clinic hours in this neighborhood.'}</p>
            </div>

            <!-- Community Health Need Indicators -->
            <div class="grid grid-cols-3 gap-2 text-center bg-slate-50 p-3 rounded-xl border border-slate-200/80">
              <div>
                <div class="text-xs text-slate-500 font-medium">Uninsured</div>
                <div class="text-sm font-bold text-slate-900">${Number(stop.pct_uninsured).toFixed(1)}%</div>
              </div>
              <div class="border-x border-slate-200">
                <div class="text-xs text-slate-500 font-medium">Asthma Rate</div>
                <div class="text-sm font-bold text-amber-700">${Number(stop.pct_asthma).toFixed(1)}%</div>
              </div>
              <div>
                <div class="text-xs text-slate-500 font-medium">Diabetes</div>
                <div class="text-sm font-bold text-rose-700">${Number(stop.pct_diabetes).toFixed(1)}%</div>
              </div>
            </div>

            <!-- Transit & Weather Setup -->
            <div class="space-y-2 text-xs">
              <div class="flex items-center justify-between flex-wrap gap-2">
                <span class="text-slate-500 font-medium"><i class="fa-solid fa-train-subway mr-1"></i> Transit Access:</span>
                <div class="flex flex-wrap gap-1">${subways} ${buses}</div>
              </div>
              <div class="bg-amber-50/70 border border-amber-200/80 rounded-lg p-2.5 flex items-center justify-between flex-wrap gap-2">
                <div class="flex items-center gap-1.5 font-semibold text-amber-900">
                  <i class="fa-solid fa-cloud-sun text-amber-600"></i>
                  <span>${stop.van_setup_mode}</span>
                </div>
                <span class="text-xs font-medium text-amber-800 bg-amber-100/80 px-2 py-0.5 rounded">
                  ${tempStr} • ${aqiStr} • ${rainStr}
                </span>
              </div>
            </div>

            <!-- Onboard Medical Kits -->
            <div>
              <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Onboard Medical Supplies</div>
              <div class="grid grid-cols-1 gap-1.5">${kitsHtml}</div>
            </div>
          </div>
        </div>

        <!-- Card Action Footer -->
        <div class="bg-slate-50 px-5 py-3 border-t border-slate-200 flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <button onclick="openFlyerForStop(${stop.saturday_index})" class="text-xs bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 font-semibold px-3 py-1.5 rounded-lg transition flex items-center gap-1.5">
              <i class="fa-solid fa-print text-teal-600"></i> Print Flyer
            </button>
            <button onclick="focusStopOnMap(${stop.lat}, ${stop.lon})" class="text-xs bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 font-semibold px-3 py-1.5 rounded-lg transition flex items-center gap-1.5">
              <i class="fa-solid fa-map-pin text-emerald-600"></i> View Map
            </button>
            <a href="${gmapsUrl}" target="_blank" rel="noopener noreferrer" class="text-xs bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 font-semibold px-2.5 py-1.5 rounded-lg transition flex items-center gap-1">
              <i class="fa-solid fa-arrow-up-right-from-square text-sky-600"></i> Google Maps
            </a>
          </div>
          <button onclick="openReplanStopModal('${stop.id}', ${stop.saturday_index}, '${stop.neighborhood.replace(/'/g, "\\'")}')" class="text-xs bg-amber-50 hover:bg-amber-100 text-amber-900 border border-amber-300 font-semibold px-3 py-1.5 rounded-lg transition flex items-center gap-1.5">
            <i class="fa-solid fa-route"></i> Relocate Stop
          </button>
        </div>
      </div>`;
    })
    .join('');
}

// Open Flyer Tab for a specific Saturday
function openFlyerForStop(satIndex) {
  selectedFlyerSatIndex = satIndex;
  switchTab('flyers');
  renderFlyerStudio();
}

// Render Tab 3: Bilingual Flyer Studio & SMS Center
function renderFlyerStudio() {
  const flyers = (currentSchedule && currentSchedule.flyers) || [];
  const stops = (currentSchedule && currentSchedule.stops) || [];

  // Render Saturday Selector Pills
  const selectorBar = document.getElementById('flyer-sat-selector');
  if (selectorBar && stops.length > 0) {
    selectorBar.innerHTML = stops
      .map((s) => {
        const active = s.saturday_index === selectedFlyerSatIndex;
        return `<button onclick="selectFlyerSaturday(${s.saturday_index})" class="px-4 py-2 rounded-xl text-xs font-bold transition flex items-center gap-2 ${
          active
            ? 'bg-emerald-600 text-white shadow-sm'
            : 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50'
        }">
          <span>Saturday ${s.saturday_index} (${s.saturday_date})</span>
          <span class="opacity-80">• ${s.neighborhood}</span>
        </button>`;
      })
      .join('');
  }

  const flyer =
    flyers.find((f) => f.saturday_index === selectedFlyerSatIndex) || flyers[0];
  if (!flyer) return;

  document.getElementById('flyer-headline-en').textContent = flyer.headline_en || '';
  document.getElementById('flyer-body-en').textContent = flyer.body_en || '';
  document.getElementById('flyer-headline-es').textContent = flyer.headline_es || '';
  document.getElementById('flyer-body-es').textContent = flyer.body_es || '';

  const posterImg = document.getElementById('flyer-poster-img');
  if (posterImg) {
    posterImg.src = `/static/flyers/saturday_${selectedFlyerSatIndex}.png`;
    posterImg.onerror = () => {
      posterImg.src = '/static/flyers/saturday_1.png';
    };
  }

  const smsEn = flyer.sms_en || '';
  const smsEs = flyer.sms_es || '';
  document.getElementById('sms-en').textContent = smsEn;
  document.getElementById('sms-es').textContent = smsEs;
  document.getElementById('sms-en-count').textContent = `${smsEn.length} / 160 chars`;
  document.getElementById('sms-es-count').textContent = `${smsEs.length} / 160 chars`;

  document.getElementById('chw-en').textContent = flyer.chw_script_en || '';
  document.getElementById('chw-es').textContent = flyer.chw_script_es || '';
}

function selectFlyerSaturday(satIndex) {
  selectedFlyerSatIndex = satIndex;
  renderFlyerStudio();
}

function copyText(elementId, label = 'Text') {
  const el = document.getElementById(elementId);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent);
  showToast(`${label} copied to clipboard!`);
}

// Tab 2: Interactive Care Desert Map (Google Maps Primary with Leaflet Fallback)

// Global callback triggered if Google Maps API finishes loading
window.onGoogleMapsInit = function () {
  console.log('Google Maps API script initialized.');
  const badge = document.getElementById('map-engine-badge');
  if (badge) {
    badge.innerHTML = `<i class="fa-solid fa-map-location-dot text-emerald-600"></i> Google Maps Active`;
  }
  const target = document.getElementById('tab-map-tab');
  if (target && target.classList.contains('active')) {
    initOrRefreshMap();
  }
};

async function initOrRefreshMap() {
  const mapEl = document.getElementById('map');
  if (!mapEl) return;

  if (!mapGeoData) {
    try {
      const res = await fetch('/api/geo/data');
      if (res.ok) {
        mapGeoData = await res.json();
      }
    } catch (err) {
      console.error('Error loading map geo data:', err);
    }
  }

  // Primary: Google Maps JavaScript API
  if (window.google && window.google.maps && window.google.maps.Map) {
    initGoogleMaps(mapEl);
    return;
  }

  // Secondary fallback: Leaflet
  if (typeof L !== 'undefined') {
    initLeafletMaps(mapEl);
    return;
  }

  console.warn('Map engine not ready yet. Retrying in 200ms...');
  setTimeout(initOrRefreshMap, 200);
}

function initGoogleMaps(mapEl) {
  isGoogleMaps = true;
  const bronxCenter = { lat: 40.8448, lng: -73.8648 };

  if (!googleMapInstance) {
    // Reset any Leaflet internal state if container previously used Leaflet
    if (mapEl._leaflet_id) {
      mapEl._leaflet_id = null;
      mapEl.innerHTML = '';
    }

    googleMapInstance = new google.maps.Map(mapEl, {
      center: bronxCenter,
      zoom: 12,
      mapTypeId: 'roadmap',
      mapTypeControl: true,
      mapTypeControlOptions: {
        style: google.maps.MapTypeControlStyle.HORIZONTAL_BAR,
        position: google.maps.ControlPosition.TOP_RIGHT,
      },
      streetViewControl: true,
      fullscreenControl: true,
      zoomControl: true,
      gestureHandling: 'cooperative',
      styles: [
        { featureType: 'poi.medical', elementType: 'geometry', stylers: [{ color: '#dbeafe' }] },
        { featureType: 'transit.station', elementType: 'labels.icon', stylers: [{ visibility: 'on' }] },
      ],
    });

    googleInfoWindow = new google.maps.InfoWindow({
      maxWidth: 340,
    });

    google.maps.event.addListener(googleMapInstance, 'click', () => {
      if (googleInfoWindow) googleInfoWindow.close();
    });

    const badge = document.getElementById('map-engine-badge');
    if (badge) {
      badge.innerHTML = `<i class="fa-solid fa-map-location-dot text-emerald-600"></i> Google Maps Active`;
      badge.className = 'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-50 text-emerald-800 border border-emerald-200';
    }
  }

  setTimeout(() => {
    if (googleMapInstance) {
      google.maps.event.trigger(googleMapInstance, 'resize');
    }
  }, 100);
  setTimeout(() => {
    if (googleMapInstance) {
      google.maps.event.trigger(googleMapInstance, 'resize');
    }
  }, 300);

  plotGoogleMapMarkers();
}

function plotGoogleMapMarkers() {
  if (!googleMapInstance) return;

  // Clear existing markers/circles
  Object.values(googleMapLayers).forEach((arr) => {
    arr.forEach((m) => {
      if (m && m.setMap) m.setMap(null);
    });
  });
  googleMapLayers = {
    stops: [],
    clinics: [],
    tracts: [],
    outliers: [],
  };

  // 1. Plot 347 Census Tracts (High-Need Care Deserts)
  if (mapGeoData && mapGeoData.tracts) {
    mapGeoData.tracts.forEach((t) => {
      const lat = Number(t.latitude != null ? t.latitude : t.lat);
      const lon = Number(t.longitude != null ? t.longitude : t.lon);
      if (isNaN(lat) || isNaN(lon)) return;
      const asthma = Number(t.pct_asthma || 0);
      const uninsured = Number(t.pct_uninsured || 0);
      const isHighBurden = asthma >= 15.5 || uninsured >= 18.0;
      const color = isHighBurden ? '#f59e0b' : '#94a3b8';

      const circle = new google.maps.Circle({
        map: googleMapInstance,
        center: { lat, lng: lon },
        radius: isHighBurden ? 210 : 150,
        fillColor: color,
        fillOpacity: isHighBurden ? 0.45 : 0.2,
        strokeColor: color,
        strokeWeight: 1,
        clickable: true,
        zIndex: 5,
      });

      circle.addListener('click', (ev) => {
        googleInfoWindow.setContent(`
          <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.45;padding:4px;">
            <div style="font-weight:bold;color:#0f172a;font-size:13px;border-bottom:1px solid #e2e8f0;padding-bottom:4px;margin-bottom:6px;">
              Census Tract Zone ${t.geo_id}
            </div>
            <div>Residents: <b>${(t.total_pop || 0).toLocaleString()}</b></div>
            <div>Asthma Rate: <b style="color:#b45309;">${asthma.toFixed(1)}%</b></div>
            <div>Uninsured Rate: <b style="color:#0f766e;">${uninsured.toFixed(1)}%</b></div>
            <div>Diabetes Rate: <b>${Number(t.pct_diabetes || 0).toFixed(1)}%</b></div>
            <div style="margin-top:6px;font-size:11px;color:${isHighBurden ? '#b45309' : '#64748b'};font-weight:600;">
              ${isHighBurden ? '⚠️ High Chronic Disease & Coverage Burden' : 'Standard Baseline Need'}
            </div>
          </div>
        `);
        googleInfoWindow.setPosition(ev.latLng || { lat, lng: lon });
        googleInfoWindow.open(googleMapInstance);
      });

      googleMapLayers.tracts.push(circle);
    });
  }

  // 2. Plot 252 Fixed Clinics (Operating Hours Gap)
  if (mapGeoData && mapGeoData.care_sites) {
    mapGeoData.care_sites.forEach((c) => {
      const lat = Number(c.lat != null ? c.lat : c.LAT);
      const lon = Number(c.lon != null ? c.lon : c.LON);
      if (isNaN(lat) || isNaN(lon)) return;
      const name = c.site_name || c.SITE_NAME || 'Community Clinic';
      const addr = c.site_address || c.SITE_ADDRESS || '';
      const hrs = Number(c.oper_hours_per_week != null ? c.oper_hours_per_week : (c.TOT_OPER_HR_PER_WEEK != null ? c.TOT_OPER_HR_PER_WEEK : c.tot_oper_hr_per_week || 40));
      const isLimited = hrs < 40;

      const marker = new google.maps.Marker({
        position: { lat, lng: lon },
        map: googleMapInstance,
        title: name,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: isLimited ? 5.5 : 4.5,
          fillColor: isLimited ? '#eab308' : '#0284c7',
          fillOpacity: 0.9,
          strokeColor: '#ffffff',
          strokeWeight: 1.5,
        },
        zIndex: 10,
      });

      marker.addListener('click', () => {
        googleInfoWindow.setContent(`
          <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.45;padding:4px;">
            <div style="font-weight:bold;color:#0f172a;font-size:13px;border-bottom:1px solid #e2e8f0;padding-bottom:4px;margin-bottom:6px;">
              ${name}
            </div>
            <div style="color:#475569;margin-bottom:4px;">${addr}</div>
            <div>Weekly Operating Hours: <b>${hrs} hrs/wk</b></div>
            <div style="margin-top:6px;font-size:11px;font-weight:bold;padding:4px 8px;border-radius:6px;background:${isLimited ? '#fef3c7;color:#92400e;' : '#e0f2fe;color:#0369a1;'}">
              ${isLimited ? '⚠️ Closed Saturdays (<40 hrs/wk) — Mobile Van Gap' : '✓ Full-Time Fixed Primary Care Clinic'}
            </div>
          </div>
        `);
        googleInfoWindow.open(googleMapInstance, marker);
      });

      googleMapLayers.clinics.push(marker);
    });
  }

  // 3. Plot Institutional Outliers (Trap 2: Rikers Island & Bronx Psych Center)
  if (mapGeoData && mapGeoData.institutional_outliers) {
    mapGeoData.institutional_outliers.forEach((o) => {
      const circle = new google.maps.Circle({
        map: googleMapInstance,
        center: { lat: o.lat, lng: o.lon },
        radius: 650,
        fillColor: '#ef4444',
        fillOpacity: 0.35,
        strokeColor: '#991b1b',
        strokeWeight: 2,
        clickable: true,
        zIndex: 15,
      });

      const marker = new google.maps.Marker({
        position: { lat: o.lat, lng: o.lon },
        map: googleMapInstance,
        title: o.name,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 9,
          fillColor: '#ef4444',
          fillOpacity: 1.0,
          strokeColor: '#ffffff',
          strokeWeight: 2,
        },
        zIndex: 25,
      });

      const showOutlierInfo = () => {
        googleInfoWindow.setContent(`
          <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.45;padding:4px;">
            <div style="font-weight:bold;color:#991b1b;font-size:13px;border-bottom:1px solid #fee2e2;padding-bottom:4px;margin-bottom:6px;">
              <i class="fa-solid fa-triangle-exclamation" style="margin-right:4px;"></i> Excluded Facility: ${o.name}
            </div>
            <div>Group Quarters Pop: <b>${o.pct_group_quarters}%</b></div>
            <div style="margin-top:6px;padding:6px;background:#fee2e2;color:#991b1b;border-radius:6px;font-size:11px;line-height:1.35;border:1px solid #fca5a5;">
              <b>Trap 2 Siting Guardrail:</b> ${o.rejection_reason}
            </div>
          </div>
        `);
        googleInfoWindow.open(googleMapInstance, marker);
      };

      circle.addListener('click', showOutlierInfo);
      marker.addListener('click', showOutlierInfo);

      googleMapLayers.outliers.push(circle);
      googleMapLayers.outliers.push(marker);
    });
  }

  // 4. Plot 4 Active Saturday Mobile Van Stops
  const stops = (currentSchedule && currentSchedule.stops) || [];
  stops.forEach((s) => {
    const lat = Number(s.lat);
    const lon = Number(s.lon);
    if (isNaN(lat) || isNaN(lon)) return;

    const stopIcon = {
      url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(`
        <svg xmlns="http://www.w3.org/2000/svg" width="38" height="48" viewBox="0 0 38 48">
          <defs>
            <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000000" flood-opacity="0.4"/>
            </filter>
          </defs>
          <path d="M19 1C9.6 1 2 8.6 2 18c0 13 17 28 17 28s17-15 17-28C36 8.6 28.4 1 19 1z" fill="#059669" stroke="#ffffff" stroke-width="2.5" filter="url(#shadow)"/>
          <circle cx="19" cy="18" r="12" fill="#ffffff"/>
          <text x="19" y="23" font-size="12" font-family="system-ui, -apple-system, sans-serif" font-weight="900" fill="#065f46" text-anchor="middle">S${s.saturday_index}</text>
        </svg>
      `),
      scaledSize: new google.maps.Size(38, 48),
      anchor: new google.maps.Point(19, 48),
    };

    const marker = new google.maps.Marker({
      position: { lat, lng: lon },
      map: googleMapInstance,
      title: `Saturday ${s.saturday_index}: ${s.neighborhood}`,
      icon: stopIcon,
      zIndex: 100,
      animation: google.maps.Animation.DROP,
    });

    const gmapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(s.street_intersection || (lat + ',' + lon))}`;
    const gmapsDir = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(s.street_intersection || (lat + ',' + lon))}`;

    marker.addListener('click', () => {
      googleInfoWindow.setContent(`
        <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.45;padding:4px;max-width:280px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <span style="background:#059669;color:white;font-weight:800;font-size:11px;padding:2px 6px;border-radius:4px;">
              Saturday ${s.saturday_index}
            </span>
            <span style="font-size:11px;color:#64748b;font-weight:600;">${s.saturday_date}</span>
          </div>
          <div style="font-weight:bold;color:#0f172a;font-size:14px;margin-top:2px;">${s.neighborhood}</div>
          <div style="font-weight:600;color:#047857;margin-top:2px;">${s.landmark_name}</div>
          <div style="color:#64748b;font-size:11px;">${s.street_intersection}</div>
          <div style="background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;padding:6px;border-radius:6px;margin-top:6px;font-size:11px;line-height:1.35;">
            <b>Clinical Siting Rationale:</b> ${s.siting_rationale}
          </div>
          <div style="display:flex;gap:6px;margin-top:8px;">
            <a href="${gmapsDir}" target="_blank" rel="noopener noreferrer" style="flex:1;text-align:center;background:#059669;color:white;text-decoration:none;font-weight:bold;padding:5px 8px;border-radius:6px;font-size:11px;">
              Directions
            </a>
            <a href="${gmapsUrl}" target="_blank" rel="noopener noreferrer" style="flex:1;text-align:center;background:#f1f5f9;color:#334155;text-decoration:none;font-weight:bold;padding:5px 8px;border-radius:6px;font-size:11px;border:1px solid #cbd5e1;">
              Google Maps
            </a>
          </div>
        </div>
      `);
      googleInfoWindow.open(googleMapInstance, marker);
      renderMapStopInspector(s);
    });

    googleMapLayers.stops.push(marker);
  });

  if (stops.length > 0) {
    renderMapStopInspector(stops[0]);
  }
}

// Leaflet Fallback Implementation
function initLeafletMaps(mapEl) {
  isGoogleMaps = false;
  if (!mapInstance) {
    try {
      if (mapEl._leaflet_id) {
        mapEl._leaflet_id = null;
      }
      mapInstance = L.map('map', {
        zoomControl: true,
        scrollWheelZoom: true,
      }).setView([40.8448, -73.8648], 12);

      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19,
      }).addTo(mapInstance);

      mapLayerGroups.tracts = L.layerGroup().addTo(mapInstance);
      mapLayerGroups.clinics = L.layerGroup().addTo(mapInstance);
      mapLayerGroups.outliers = L.layerGroup().addTo(mapInstance);
      mapLayerGroups.stops = L.layerGroup().addTo(mapInstance);
    } catch (err) {
      console.error('Error initializing Leaflet map:', err);
    }
  }

  setTimeout(() => mapInstance && mapInstance.invalidateSize(), 80);
  setTimeout(() => mapInstance && mapInstance.invalidateSize(), 250);

  plotMapMarkers();
}

function plotMapMarkers() {
  if (!mapInstance) return;
  Object.values(mapLayerGroups).forEach((lg) => lg && lg.clearLayers());

  if (mapGeoData && mapGeoData.tracts) {
    mapGeoData.tracts.forEach((t) => {
      const lat = Number(t.latitude != null ? t.latitude : t.lat);
      const lon = Number(t.longitude != null ? t.longitude : t.lon);
      if (isNaN(lat) || isNaN(lon)) return;
      const asthma = Number(t.pct_asthma || 0);
      const uninsured = Number(t.pct_uninsured || 0);
      const isHighBurden = asthma >= 15.5 || uninsured >= 18.0;
      const color = isHighBurden ? '#f59e0b' : '#94a3b8';

      L.circleMarker([lat, lon], {
        radius: isHighBurden ? 5 : 3.5,
        fillColor: color,
        color: color,
        weight: 1,
        fillOpacity: isHighBurden ? 0.55 : 0.25,
      })
        .bindPopup(
          `<div class="text-xs space-y-1">
            <div class="font-bold text-slate-900">Neighborhood Census Zone ${t.geo_id}</div>
            <div>Residents: <b>${(t.total_pop || 0).toLocaleString()}</b></div>
            <div>Asthma Rate: <b>${asthma.toFixed(1)}%</b> | Uninsured: <b>${uninsured.toFixed(1)}%</b></div>
            <div>Diabetes Rate: <b>${Number(t.pct_diabetes || 0).toFixed(1)}%</b></div>
          </div>`
        )
        .addTo(mapLayerGroups.tracts);
    });
  }

  if (mapGeoData && mapGeoData.care_sites) {
    mapGeoData.care_sites.forEach((c) => {
      const lat = Number(c.lat != null ? c.lat : c.LAT);
      const lon = Number(c.lon != null ? c.lon : c.LON);
      if (isNaN(lat) || isNaN(lon)) return;
      const name = c.site_name || c.SITE_NAME || 'Community Clinic';
      const addr = c.site_address || c.SITE_ADDRESS || '';
      const hrs = Number(c.oper_hours_per_week != null ? c.oper_hours_per_week : (c.TOT_OPER_HR_PER_WEEK != null ? c.TOT_OPER_HR_PER_WEEK : c.tot_oper_hr_per_week || 40));
      const isLimited = hrs < 40;

      L.circleMarker([lat, lon], {
        radius: 5,
        fillColor: isLimited ? '#eab308' : '#0284c7',
        color: '#ffffff',
        weight: 1,
        fillOpacity: 0.85,
      })
        .bindPopup(
          `<div class="text-xs space-y-1">
            <div class="font-bold text-slate-900">${name}</div>
            <div>Address: ${addr}</div>
            <div>Weekly Operating Hours: <b>${hrs} hrs/wk</b></div>
            <div class="text-amber-700 font-semibold">${
              isLimited ? 'Limited Weekday Hours (Closed Saturdays)' : 'Standard Fixed Clinic'
            }</div>
          </div>`
        )
        .addTo(mapLayerGroups.clinics);
    });
  }

  if (mapGeoData && mapGeoData.institutional_outliers) {
    mapGeoData.institutional_outliers.forEach((o) => {
      L.circleMarker([o.lat, o.lon], {
        radius: 10,
        fillColor: '#ef4444',
        color: '#7f1d1d',
        weight: 2,
        fillOpacity: 0.9,
      })
        .bindPopup(
          `<div class="text-xs space-y-1">
            <div class="font-bold text-red-700">Excluded Facility: ${o.name}</div>
            <div>Group Quarters Population: <b>${o.pct_group_quarters}%</b></div>
            <div class="text-slate-700">${o.rejection_reason}</div>
          </div>`
        )
        .addTo(mapLayerGroups.outliers);
    });
  }

  const stops = (currentSchedule && currentSchedule.stops) || [];
  stops.forEach((s) => {
    const lat = Number(s.lat);
    const lon = Number(s.lon);
    if (isNaN(lat) || isNaN(lon)) return;

    const icon = L.divIcon({
      className: 'custom-stop-pin',
      html: `<div style="background:#059669;color:white;width:32px;height:32px;border-radius:9999px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;border:3px solid white;box-shadow:0 4px 10px rgba(0,0,0,0.35);">S${s.saturday_index}</div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16],
    });

    const gmapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(s.street_intersection || (lat + ',' + lon))}`;

    const marker = L.marker([lat, lon], { icon })
      .bindPopup(
        `<div class="text-xs space-y-1.5">
          <div class="font-bold text-emerald-800 text-sm">Saturday ${s.saturday_index}: ${s.neighborhood}</div>
          <div class="font-semibold text-slate-800">${s.landmark_name}</div>
          <div class="text-slate-600">${s.street_intersection}</div>
          <div class="bg-emerald-50 p-2 rounded border border-emerald-200 text-slate-700">${s.siting_rationale}</div>
          <div class="pt-1">
            <a href="${gmapsUrl}" target="_blank" rel="noopener noreferrer" class="text-emerald-700 font-bold hover:underline inline-flex items-center gap-1">
              <i class="fa-solid fa-arrow-up-right-from-square"></i> Open in Google Maps
            </a>
          </div>
        </div>`
      )
      .addTo(mapLayerGroups.stops);

    marker.on('click', () => renderMapStopInspector(s));
  });

  if (stops.length > 0) {
    renderMapStopInspector(stops[0]);
  }
}

function toggleMapLayer(layerName, visible) {
  if (isGoogleMaps && googleMapLayers[layerName]) {
    googleMapLayers[layerName].forEach((obj) => {
      if (obj && obj.setMap) obj.setMap(visible ? googleMapInstance : null);
    });
  }
  if (mapInstance && mapLayerGroups[layerName]) {
    if (visible) {
      mapLayerGroups[layerName].addTo(mapInstance);
    } else {
      mapInstance.removeLayer(mapLayerGroups[layerName]);
    }
  }
}

function focusStopOnMap(lat, lon) {
  switchTab('map-tab');
  setTimeout(() => {
    if (isGoogleMaps && googleMapInstance) {
      googleMapInstance.setCenter({ lat: Number(lat), lng: Number(lon) });
      googleMapInstance.setZoom(16);
      const matched = googleMapLayers.stops.find((m) => {
        if (!m || !m.getPosition) return false;
        const p = m.getPosition();
        return Math.abs(p.lat() - Number(lat)) < 0.001 && Math.abs(p.lng() - Number(lon)) < 0.001;
      });
      if (matched && window.google && window.google.maps) {
        google.maps.event.trigger(matched, 'click');
      }
    } else if (mapInstance) {
      mapInstance.setView([lat, lon], 15);
      mapInstance.invalidateSize();
    }
  }, 200);
}

function renderMapStopInspector(stop) {
  const el = document.getElementById('map-stop-inspector');
  if (!el || !stop) return;
  const gmapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(stop.street_intersection || (stop.lat + ',' + stop.lon))}`;
  const earthUrl = `https://earth.google.com/web/search/${encodeURIComponent(stop.street_intersection || stop.landmark_name)}`;

  el.innerHTML = `
    <div class="space-y-3">
      <div class="flex items-center justify-between">
        <span class="bg-emerald-600 text-white text-xs font-bold px-2.5 py-1 rounded">Saturday ${stop.saturday_index} • ${stop.saturday_date}</span>
        <span class="text-xs font-semibold text-slate-500">${stop.hpsa_name}</span>
      </div>
      <div>
        <h4 class="text-base font-bold text-slate-900">${stop.neighborhood}</h4>
        <p class="text-xs font-semibold text-emerald-700 mt-0.5">${stop.landmark_name}</p>
        <p class="text-xs text-slate-500">${stop.street_intersection}</p>
      </div>
      <div class="bg-slate-50 p-3 rounded-xl border border-slate-200 text-xs space-y-1">
        <div class="font-bold text-slate-800">Why Selected:</div>
        <p class="text-slate-600 leading-relaxed">${stop.siting_rationale}</p>
      </div>
      <div class="grid grid-cols-3 gap-2 text-center text-xs bg-white p-2.5 rounded-lg border border-slate-200">
        <div><div class="text-slate-500">Uninsured</div><div class="font-bold text-slate-900">${Number(stop.pct_uninsured).toFixed(1)}%</div></div>
        <div><div class="text-slate-500">Asthma</div><div class="font-bold text-amber-700">${Number(stop.pct_asthma).toFixed(1)}%</div></div>
        <div><div class="text-slate-500">Diabetes</div><div class="font-bold text-rose-700">${Number(stop.pct_diabetes).toFixed(1)}%</div></div>
      </div>
      <div class="flex items-center gap-2 pt-1">
        <a href="${gmapsUrl}" target="_blank" rel="noopener noreferrer" class="flex-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 font-semibold text-center text-xs py-2 rounded-lg transition inline-flex items-center justify-center gap-1.5">
          <i class="fa-solid fa-map-location-dot text-emerald-600"></i> Google Maps
        </a>
        <a href="${earthUrl}" target="_blank" rel="noopener noreferrer" class="flex-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 font-semibold text-center text-xs py-2 rounded-lg transition inline-flex items-center justify-center gap-1.5">
          <i class="fa-solid fa-earth-americas text-sky-600"></i> Earth 3D
        </a>
      </div>
      <button onclick="openFlyerForStop(${stop.saturday_index})" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs py-2 rounded-lg transition">
        <i class="fa-solid fa-bullhorn mr-1"></i> Open Bilingual Flyer Studio
      </button>
    </div>
  `;
}

// Render Tab 4: Health Equity Governance & Audit Trail
async function renderGovernanceAudit() {
  if (!currentSchedule) return;
  const briefingEl = document.getElementById('director-briefing-text');
  if (briefingEl) {
    briefingEl.textContent =
      currentSchedule.director_briefing ||
      currentSchedule.summary ||
      'Schedule audited for demographic equity and zero institutional group-quarters outliers.';
  }

  const timelineEl = document.getElementById('audit-timeline-list');
  if (!timelineEl) return;

  try {
    const res = await fetch(`/api/audit/logs?schedule_id=${currentSchedule.id}`);
    const logs = res.ok ? await res.json() : currentSchedule.audit_logs || [];
    const sorted = [...logs].sort((a, b) => a.iteration_number - b.iteration_number);

    timelineEl.innerHTML = sorted
      .map((log) => {
        const isRejected = log.audit_status === 'REJECTED';
        const isModified = log.audit_status === 'HITL_MODIFIED';
        const badgeClass = isRejected
          ? 'bg-red-100 text-red-800 border-red-300'
          : isModified
          ? 'bg-amber-100 text-amber-800 border-amber-300'
          : 'bg-emerald-100 text-emerald-800 border-emerald-300';

        const violations = (log.violations || [])
          .map((v) => `<li class="text-red-700 font-medium">• ${v}</li>`)
          .join('');

        return `
        <div class="bg-white rounded-xl border border-slate-200 p-4 shadow-sm space-y-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <span class="font-bold text-sm text-slate-900">Review Step #${log.iteration_number}</span>
              <span class="text-xs px-2.5 py-0.5 rounded-full font-bold border ${badgeClass}">
                ${log.audit_status === 'REJECTED' ? 'Flagged & Auto-Corrected' : log.audit_status === 'HITL_MODIFIED' ? 'Coordinator Relocation' : 'Equity Verified & Approved'}
              </span>
            </div>
            <span class="text-xs text-slate-500">${log.hpsa_diversity_status || '4 Distinct Shortage Zones'}</span>
          </div>
          <p class="text-xs text-slate-700 leading-relaxed">${log.auditor_comments}</p>
          ${violations ? `<ul class="text-xs space-y-1 bg-red-50 p-2.5 rounded-lg border border-red-200">${violations}</ul>` : ''}
        </div>`;
      })
      .join('');
  } catch (err) {
    console.error('Error rendering audit logs:', err);
  }
}

// Whole-Plan Approve Action
async function approveWholeSchedule() {
  if (!currentSchedule) return;
  try {
    const res = await fetch('/api/admin/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schedule_id: currentSchedule.id,
        action_type: 'APPROVE',
        admin_user: 'Clinical Coordinator',
      }),
    });
    if (res.ok) {
      currentSchedule.status = 'APPROVED';
      renderKpiSummary();
      await loadScheduleHistory();
      showToast('Deployment schedule officially approved for mobile van dispatch!');
    }
  } catch (err) {
    showToast('Error approving schedule', 'error');
  }
}

// Per-Stop Relocation Modal (Human-in-the-Loop)
function openReplanStopModal(stopId, satIndex, neighborhood) {
  activeReplanStopId = stopId;
  document.getElementById('replan-modal-title').textContent = `Relocate Saturday ${satIndex} (${neighborhood})`;
  document.getElementById('replan-reason-input').value = '';
  document.getElementById('replan-modal').classList.remove('hidden');
}

function closeReplanStopModal() {
  activeReplanStopId = null;
  document.getElementById('replan-modal').classList.add('hidden');
}

async function submitReplanStop() {
  if (!currentSchedule || !activeReplanStopId) return;
  const category = document.getElementById('replan-category-select').value;
  const reason =
    document.getElementById('replan-reason-input').value.trim() ||
    'Coordinator requested alternate accessible street corner';

  const btn = document.getElementById('replan-submit-btn');
  btn.disabled = true;
  btn.textContent = 'Selecting Next Best Site...';

  try {
    const res = await fetch(
      `/api/schedule/${currentSchedule.id}/replan-stop/${activeReplanStopId}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rejection_category: category,
          rejection_reason: reason,
          admin_user: 'Clinical Coordinator',
        }),
      }
    );
    if (!res.ok) throw new Error('Relocation failed');
    currentSchedule = await res.json();
    closeReplanStopModal();
    renderAllViews();
    showToast('Saturday stop relocated to the next highest-need residential site!');
  } catch (err) {
    showToast('Could not relocate stop: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Confirm & Relocate Van';
  }
}

// New Monthly Plan Modal
function openNewPlanModal() {
  document.getElementById('new-plan-modal').classList.remove('hidden');
}

function closeNewPlanModal() {
  document.getElementById('new-plan-modal').classList.add('hidden');
}

async function submitGenerateNewPlan() {
  const targetMonth = document.getElementById('new-plan-month').value.trim() || 'December 2026';
  const focusNote = document.getElementById('new-plan-focus').value.trim();
  const btn = document.getElementById('new-plan-submit-btn');

  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-1.5"></i> Building & Auditing Plan (~25s)...';
  showToast(`Generating & auditing 4-Saturday plan for ${targetMonth}...`, 'info');

  try {
    const res = await fetch('/api/schedule/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_month: targetMonth,
        user_prompt: focusNote ? `Generate 4-Saturday mobile care plan for ${targetMonth}. Priority focus: ${focusNote}` : null,
      }),
    });
    if (!res.ok) throw new Error('Generation request failed');
    currentSchedule = await res.json();
    await loadScheduleHistory();
    renderAllViews();
    closeNewPlanModal();
    showToast(`New ${targetMonth} deployment schedule created and verified!`);
  } catch (err) {
    showToast('Schedule generation encountered an error: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles mr-1.5"></i> Generate Audited Schedule';
  }
}

// AI Care Copilot Chat
function askCopilotPreset(promptText) {
  const input = document.getElementById('copilot-input');
  if (input) {
    input.value = promptText;
    sendCopilotMessage();
  }
}

async function sendCopilotMessage() {
  const input = document.getElementById('copilot-input');
  const feed = document.getElementById('copilot-messages');
  if (!input || !feed) return;

  const query = input.value.trim();
  if (!query) return;
  input.value = '';

  // Append User Bubble
  const userDiv = document.createElement('div');
  userDiv.className = 'flex justify-end';
  userDiv.innerHTML = `<div class="bg-emerald-600 text-white text-xs rounded-2xl rounded-tr-sm px-3.5 py-2.5 max-w-[85%] shadow-sm">${query}</div>`;
  feed.appendChild(userDiv);

  // Append Loading Bubble
  const botDiv = document.createElement('div');
  botDiv.className = 'flex justify-start';
  botDiv.innerHTML = `<div class="bg-slate-100 text-slate-700 border border-slate-200 text-xs rounded-2xl rounded-tl-sm px-3.5 py-2.5 max-w-[90%] shadow-sm"><i class="fa-solid fa-circle-notch fa-spin text-emerald-600 mr-1.5"></i> Checking clinical & neighborhood records...</div>`;
  feed.appendChild(botDiv);
  feed.scrollTop = feed.scrollHeight;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query,
        schedule_id: currentSchedule ? currentSchedule.id : null,
      }),
    });
    const data = await res.json();
    const formatted = (data.reply || '')
      .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
      .replace(/\n/g, '<br>');

    botDiv.innerHTML = `
      <div class="bg-white text-slate-800 border border-slate-200 text-xs rounded-2xl rounded-tl-sm px-3.5 py-3 max-w-[92%] shadow-sm space-y-2 leading-relaxed">
        <div>${formatted}</div>
      </div>`;
  } catch (err) {
    botDiv.innerHTML = `<div class="bg-red-50 text-red-700 border border-red-200 text-xs rounded-2xl px-3.5 py-2.5">Unable to reach Care Copilot right now.</div>`;
  }
  feed.scrollTop = feed.scrollHeight;
}

window.addEventListener('DOMContentLoaded', loadInitialSchedule);
