let gpsMap = null;
let gpsMarker = null;
let mapHasFix = false;
let orbitGps = { latitude: null, longitude: null };
let orbitSatellites = [];
let orbitRotation = { yaw: 0, pitch: 0 };
let orbitZoom = 1;
let orbitPoints = [];
const orbitTrailHistory = new Map();
let orbitDrag = null;
const ORBIT_ICON_URLS = {
  GPS: "/static/icons/satellite-gps.svg",
  Galileo: "/static/icons/satellite-galileo.svg",
  GLONASS: "/static/icons/satellite-glonass.svg",
  BeiDou: "/static/icons/satellite-beidou.svg",
  QZSS: "/static/icons/satellite-qzss.svg",
  SBAS: "/static/icons/satellite-sbas.svg",
  NavIC: "/static/icons/satellite-navic.svg",
  IMES: "/static/icons/satellite-imes.svg"
};
const orbitIcons = Object.fromEntries(Object.entries(ORBIT_ICON_URLS).map(([name, url]) => {
  const image = new Image(); image.onload = () => drawOrbitView(); image.src = url; return [name, image];
}));
const baseStationOrbitIcon = new Image();
baseStationOrbitIcon.onload = () => drawOrbitView();
baseStationOrbitIcon.src = "/static/icons/base-station.svg";
let globeLandRings = [];
// Natural Earth ne_110m_land coastline geometry (public domain; github.com/nvkelso/natural-earth-vector).
fetch("/static/data/globe-land.json")
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(rings => { globeLandRings = rings; drawOrbitView(); })
  .catch(error => console.error('Could not load globe land outlines:', error));
let globeStarCatalog = [];
// Bright-star positions and proper motions from ESA Gaia DR3 (ICRS, reference epoch J2016.0).
fetch("/static/data/globe-stars.json")
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(stars => { globeStarCatalog = stars; drawOrbitView(); })
  .catch(error => console.error('Could not load Gaia star catalog:', error));
const orbitLegendDetails = { GPS: 'GPS · MEO', Galileo: 'Galileo · MEO', GLONASS: 'GLONASS · MEO', BeiDou: 'BeiDou · MEO*', QZSS: 'QZSS · IGSO/GEO', SBAS: 'SBAS · GEO', NavIC: 'NavIC · GEO/IGSO', IMES: 'IMES · varies' };
function initializeOrbitLegend() {
  const legend = document.getElementById('orbit-legend');
  Object.entries(ORBIT_ICON_URLS).forEach(([name, url]) => {
    const item = document.createElement('div'); item.className = 'orbit-legend-item';
    const icon = document.createElement('img'); icon.src = url; icon.alt = '';
    const label = document.createElement('span');
    const title = document.createElement('span'); title.textContent = name;
    const detail = document.createElement('small'); detail.textContent = orbitLegendDetails[name];
    label.append(title, detail); item.append(icon, label); legend.appendChild(item);
  });
}
initializeOrbitLegend();
const DOWNLOAD_ICON_URL = "/static/icons/download.svg";
let updateOutputOffset = 0;
let updatePollTimer = null;
let updateReturnTimer = null;
let updateUpgradePromptShown = false;
const trafficHistory = [];
function formatRate(bytesPerSecond) {
  if (bytesPerSecond >= 1024 ** 2) return `${(bytesPerSecond / 1024 ** 2).toFixed(2)} MiB/s`;
  if (bytesPerSecond >= 1024) return `${(bytesPerSecond / 1024).toFixed(1)} KiB/s`;
  return `${Math.round(bytesPerSecond)} B/s`;
}
function formatChartTime(milliseconds) {
  if (milliseconds >= 60000) return `${Math.round(milliseconds / 60000)}m`;
  if (milliseconds >= 10000) return `${Math.round(milliseconds / 1000)}s`;
  const seconds = milliseconds / 1000;
  return `${Number(seconds.toFixed(1))}s`;
}
function updateTrafficPanel(traffic, clientCount) {
  const rx = Number(traffic.rx_rate) || 0;
  const tx = Number(traffic.tx_rate) || 0;
  document.getElementById('flow-interface').textContent = traffic.interface;
  document.getElementById('flow-rx-rate').textContent = formatRate(rx);
  document.getElementById('flow-tx-rate').textContent = formatRate(tx);
  document.getElementById('flow-totals').textContent = `${traffic.received} / ${traffic.sent}`;
  const now = Date.now();
  trafficHistory.push({ rx, tx, time: now });
  while (trafficHistory.length > 1 && now - trafficHistory[0].time > 120000) trafficHistory.shift();
  const max = Math.max(1, ...trafficHistory.flatMap(point => [point.rx, point.tx]));
  const left = 62, right = 590, top = 12, bottom = 132;
  const firstTime = trafficHistory[0].time;
  const elapsed = Math.max(1000, now - firstTime);
  const visibleSpan = Math.min(120000, elapsed);
  const chartStart = now - visibleSpan;
  const pointsFor = key => trafficHistory.map((point, index) => {
    const x = left + Math.max(0, Math.min(1, (point.time - chartStart) / visibleSpan)) * (right - left);
    const y = bottom - point[key] / max * (bottom - top);
    return { x, y };
  });
  const writeSeries = (key, lineId, areaId) => {
    const points = pointsFor(key);
    document.getElementById(lineId).setAttribute('points', points.map(point => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' '));
    const areaPath = points.length ? `M${points[0].x.toFixed(1)} ${bottom} L${points.map(point => `${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' L')} L${points[points.length - 1].x.toFixed(1)} ${bottom} Z` : '';
    document.getElementById(areaId).setAttribute('d', areaPath);
  };
  writeSeries('rx', 'traffic-rx-line', 'traffic-rx-area');
  writeSeries('tx', 'traffic-tx-line', 'traffic-tx-area');
  const svgNs = 'http://www.w3.org/2000/svg';
  const yLabels = document.getElementById('traffic-y-labels');
  const xLabels = document.getElementById('traffic-x-labels');
  const grid = document.getElementById('traffic-grid');
  yLabels.replaceChildren(); xLabels.replaceChildren(); grid.replaceChildren();
  [0, 0.5, 1].forEach(fraction => {
    const y = bottom - fraction * (bottom - top);
    const line = document.createElementNS(svgNs, 'line');
    line.setAttribute('x1', left); line.setAttribute('x2', right); line.setAttribute('y1', y); line.setAttribute('y2', y);
    grid.appendChild(line);
    const label = document.createElementNS(svgNs, 'text');
    label.setAttribute('x', left - 7); label.setAttribute('y', y + 3); label.textContent = formatRate(max * fraction);
    yLabels.appendChild(label);
  });
  const midpoint = visibleSpan / 2;
  [[`−${formatChartTime(visibleSpan)}`, left], [`−${formatChartTime(midpoint)}`, (left + right) / 2], ['now', right]].forEach(([value, x]) => {
    const label = document.createElementNS(svgNs, 'text');
    label.setAttribute('x', x); label.setAttribute('y', 155); label.textContent = value;
    xLabels.appendChild(label);
  });
  const historyLabel = elapsed >= 120000 ? 'last 2 minutes' : `history ${Math.floor(elapsed / 1000)}s / 2 minutes`;
  document.getElementById('flow-chart-scale').textContent = `Peak ${formatRate(max)} \u00b7 ${historyLabel}`;
  document.getElementById('flow-client-count').textContent = clientCount;
}

function setPanelCollapsed(header, collapsed) {
  const panel = header.closest('.card');
  panel.classList.toggle('collapsed', collapsed);
  header.setAttribute('aria-expanded', String(!collapsed));
  try {
    localStorage.setItem(`rtk-panel:${header.textContent.trim()}`, collapsed ? 'closed' : 'open');
  } catch (error) { /* Storage can be unavailable in private browsing modes. */ }
  if (!collapsed && panel.querySelector('#gps-map') && gpsMap) {
    window.setTimeout(() => gpsMap.invalidateSize(), 50);
  }
}

function setupCollapsiblePanels() {
  document.querySelectorAll('.card > h2').forEach(header => {
    header.setAttribute('role', 'button');
    header.setAttribute('tabindex', '0');
    const key = `rtk-panel:${header.textContent.trim()}`;
    try {
      if (localStorage.getItem(key) === 'closed') {
        header.closest('.card').classList.add('collapsed');
        header.setAttribute('aria-expanded', 'false');
      } else {
        header.setAttribute('aria-expanded', 'true');
      }
    } catch (error) {
      header.setAttribute('aria-expanded', 'true');
    }
    header.addEventListener('click', () => {
      setPanelCollapsed(header, header.getAttribute('aria-expanded') === 'true');
    });
    header.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        header.click();
      }
    });
  });
}

function initializeMap() {
  const note = document.getElementById('map-note');
  if (typeof L === 'undefined') {
    note.textContent = 'Map library unavailable. The map requires an internet connection.';
    return;
  }
  gpsMap = L.map('gps-map', { scrollWheelZoom: false }).setView([0, 0], 2);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    className: 'dark-map-tiles',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(gpsMap);
  window.setTimeout(() => gpsMap.invalidateSize(), 100);
}

function updateGpsMap(gps) {
  const note = document.getElementById('map-note');
  if (!gpsMap) initializeMap();
  if (!gpsMap) return;
  const lat = gps.latitude;
  const lon = gps.longitude;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    note.textContent = 'Waiting for a valid GPS fix.';
    return;
  }
  const position = L.latLng(lat, lon);
  if (!gpsMarker) {
    const baseStationIcon = L.icon({
      iconUrl: "/static/icons/base-station.svg",
      iconSize: [40, 40], iconAnchor: [20, 20],
      tooltipAnchor: [0, -20],
      className: 'base-station-map-icon'
    });
    gpsMarker = L.marker(position, { icon: baseStationIcon }).addTo(gpsMap);
  } else {
    gpsMarker.setLatLng(position);
  }
  if (!mapHasFix) {
    gpsMap.setView(position, 15);
    mapHasFix = true;
  } else if (!gpsMap.getBounds().contains(position)) {
    gpsMap.panTo(position, { animate: false });
  }
  note.textContent = `Receiver position: ${lat.toFixed(6)}, ${lon.toFixed(6)}`;
}

function updateSatelliteGraphics(satellites) {
  const svgNamespace = 'http://www.w3.org/2000/svg';
  const plot = document.getElementById('sky-satellites');
  const list = document.getElementById('signal-list');
  const constellationList = document.getElementById('constellation-list');
  const skyLegend = document.getElementById('sky-legend');
  const shapeKinds = { GPS: 'circle', SBAS: 'square', Galileo: 'triangle', BeiDou: 'diamond', IMES: 'pentagon', QZSS: 'hexagon', GLONASS: 'plus', NavIC: 'star' };
  const constellationOf = satellite => String(satellite.id || 'Unknown').replace(/\s+\S+$/, '');
  const constellationCountry = name => ({ GPS: 'United States', Galileo: 'European Union', GLONASS: 'Russia', BeiDou: 'China', QZSS: 'Japan', NavIC: 'India', IMES: 'Japan', SBAS: 'Regional system (multiple countries)' })[name] || 'Unknown';
  const signalClass = signal => signal < 20 ? 'signal-weak' : signal < 30 ? 'signal-fair' : signal < 40 ? 'signal-good' : 'signal-strong';
  const appendShape = (svg, name, className, radius = 5) => {
    const kind = shapeKinds[name] || 'circle';
    let shape;
    if (kind === 'circle') {
      shape = document.createElementNS(svgNamespace, 'circle');
      shape.setAttribute('r', radius);
    } else if (kind === 'square') {
      shape = document.createElementNS(svgNamespace, 'rect');
      shape.setAttribute('x', -radius); shape.setAttribute('y', -radius);
      shape.setAttribute('width', radius * 2); shape.setAttribute('height', radius * 2);
    } else {
      const sides = { triangle: 3, diamond: 4, pentagon: 5, hexagon: 6, star: 10 }[kind] || 3;
      const points = kind === 'plus'
        ? [[-radius * .35, -radius], [radius * .35, -radius], [radius * .35, -radius * .35], [radius, -radius * .35], [radius, radius * .35], [radius * .35, radius * .35], [radius * .35, radius], [-radius * .35, radius], [-radius * .35, radius * .35], [-radius, radius * .35], [-radius, -radius * .35], [-radius * .35, -radius * .35]]
            .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
        : Array.from({ length: sides }, (_, index) => {
            const angle = -Math.PI / 2 + index * Math.PI * 2 / sides;
            const pointRadius = kind === 'star' && index % 2 ? radius * 0.45 : radius;
            return `${(Math.cos(angle) * pointRadius).toFixed(1)},${(Math.sin(angle) * pointRadius).toFixed(1)}`;
          }).join(' ');
      shape = document.createElementNS(svgNamespace, 'polygon');
      shape.setAttribute('points', points);
    }
    shape.setAttribute('class', className);
    svg.appendChild(shape);
    return shape;
  };
  while (plot.firstChild) plot.removeChild(plot.firstChild);
  list.replaceChildren();
  constellationList.replaceChildren();
  skyLegend.replaceChildren();
  Object.entries(ORBIT_ICON_URLS).forEach(([name, url]) => {
    const legendItem = document.createElement('span');
    legendItem.className = 'sky-legend-item';
    const icon = document.createElementNS(svgNamespace, 'svg');
    icon.setAttribute('viewBox', '0 0 64 64');
    const image = document.createElementNS(svgNamespace, 'image');
    image.setAttribute('href', url); image.setAttribute('width', '64'); image.setAttribute('height', '64');
    icon.appendChild(image);
    legendItem.append(icon, document.createTextNode(name));
    skyLegend.appendChild(legendItem);
  });
  if (!satellites || satellites.length === 0) {
    list.textContent = 'No satellite data available';
    constellationList.textContent = 'No constellation data available';
    return;
  }
  const constellations = new Map();
  satellites.forEach(sat => {
    const name = constellationOf(sat);
    const entry = constellations.get(name) || { visible: 0, used: 0, satellites: [] };
    entry.visible += 1;
    if (sat.used) entry.used += 1;
    entry.satellites.push(sat);
    constellations.set(name, entry);
  });
  [...constellations.entries()].sort((a, b) => a[0].localeCompare(b[0])).forEach(([name, counts]) => {
    const chip = document.createElement('div');
    chip.className = 'constellation-chip';
    chip.textContent = `${name} · ${counts.visible} visible`;
    const used = document.createElement('strong');
    used.textContent = `${counts.used} used`;
    chip.appendChild(used);
    constellationList.appendChild(chip);

    const group = document.createElement('section');
    group.className = 'satellite-group';
    const heading = document.createElement('h3');
    heading.textContent = name;
    group.appendChild(heading);
    const rows = document.createElement('div');
    rows.className = 'signal-list';
    counts.satellites.sort((a, b) => String(a.id).localeCompare(String(b.id), undefined, { numeric: true })).forEach(satellite => {
      const signal = Number(satellite.signal);
      const hasSignal = satellite.signal !== null && Number.isFinite(signal);
      const row = document.createElement('div');
      row.className = 'signal-row';
      const label = document.createElement('span');
      label.className = 'signal-name';
      const labelText = document.createElement('span');
      labelText.textContent = `${satellite.used ? 'USED ' : ''}${satellite.id}`;
      const countryText = document.createElement('small');
      countryText.className = 'signal-country';
      countryText.textContent = constellationCountry(name);
      label.append(labelText, countryText);
      const bars = document.createElement('div');
      const strength = hasSignal ? Math.max(0, Math.min(4, Math.ceil(signal / 10))) : 0;
      bars.className = `sat-cell ${hasSignal ? signalClass(signal) : ''}`;
      for (let index = 1; index <= 4; index += 1) {
        const bar = document.createElement('i');
        if (index <= strength) bar.className = 'on';
        bars.appendChild(bar);
      }
      const value = document.createElement('span');
      value.className = hasSignal ? signalClass(signal) : '';
      value.textContent = hasSignal ? `${signal.toFixed(0)} dB-Hz` : '—';
      row.append(label, bars, value);
      rows.appendChild(row);
    });
    group.appendChild(rows);
    list.appendChild(group);

  });
  satellites.forEach(satellite => {
    const az = Number(satellite.azimuth);
    const el = Number(satellite.elevation);
    const hasSkyPosition = satellite.azimuth !== null && satellite.elevation !== null &&
      Number.isFinite(az) && Number.isFinite(el) && el >= 0 && el <= 90;
    if (hasSkyPosition) {
      const angle = az * Math.PI / 180;
      const radius = 100 * (90 - el) / 90;
      const x = 120 + radius * Math.sin(angle);
      const y = 120 - radius * Math.cos(angle);
      const group = document.createElementNS(svgNamespace, 'g');
      const constellation = constellationOf(satellite);
      const iconUrl = ORBIT_ICON_URLS[constellation];
      if (iconUrl) {
        const icon = document.createElementNS(svgNamespace, 'image');
        icon.setAttribute('href', iconUrl);
        icon.setAttribute('x', (x - 8).toFixed(1)); icon.setAttribute('y', (y - 8).toFixed(1));
        icon.setAttribute('width', '16'); icon.setAttribute('height', '16');
        icon.setAttribute('class', satellite.used ? 'sky-satellite-icon' : 'sky-satellite-icon unused');
        group.appendChild(icon);
      } else {
        const dot = appendShape(group, constellation, satellite.used ? 'sky-sat used' : 'sky-sat', 5);
        dot.setAttribute('transform', `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
      }
      const title = document.createElementNS(svgNamespace, 'title');
      title.textContent = `${satellite.id} · ${constellationCountry(constellation)}: az ${az} deg, el ${el} deg${satellite.used ? ', used' : ''}`;
      group.appendChild(title);
      const label = document.createElementNS(svgNamespace, 'text');
      label.setAttribute('x', x.toFixed(1));
      label.setAttribute('y', (y - 8).toFixed(1));
      label.setAttribute('class', 'sky-label');
      label.textContent = satellite.id;
      group.appendChild(label);
      plot.appendChild(group);
    }
  });
}

function drawOrbitView(gps = orbitGps, satellites = orbitSatellites, sampleTrails = false) {
  const canvas = document.getElementById('orbit-view');
  const ctx = canvas.getContext('2d');
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.round(bounds.width * dpr), height = Math.round(bounds.height * dpr);
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = bounds.width, h = bounds.height;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2 + 3;
  const earthR = Math.max(82, Math.min(h * .31, w * .16, 175)) * orbitZoom;
  const rad = Math.PI / 180;
  const jd = Date.now() / 86400000 + 2440587.5;
  const gmst = ((280.46061837 + 360.98564736629 * (jd - 2451545)) % 360) * rad;
  const lat = Number(gps.latitude), lon = Number(gps.longitude);
  const hasFix = Number.isFinite(lat) && Number.isFinite(lon);
  const latR = (hasFix ? lat : 0) * Math.PI / 180;
  const lonR = (hasFix ? lon : 0) * Math.PI / 180;
  const forward = [Math.cos(latR) * Math.cos(lonR), Math.cos(latR) * Math.sin(lonR), Math.sin(latR)];
  const east = [-Math.sin(lonR), Math.cos(lonR), 0];
  const north = [-Math.sin(latR) * Math.cos(lonR), -Math.sin(latR) * Math.sin(lonR), Math.cos(latR)];
  const project = p => {
    const yaw = orbitRotation.yaw, pitch = orbitRotation.pitch;
    const x = p[0] * Math.cos(yaw) - p[2] * Math.sin(yaw);
    const yawZ = p[0] * Math.sin(yaw) + p[2] * Math.cos(yaw);
    const y = p[1] * Math.cos(pitch) - yawZ * Math.sin(pitch);
    const z = p[1] * Math.sin(pitch) + yawZ * Math.cos(pitch);
    return { x: cx + earthR * x, y: cy - earthR * y, z };
  };
  const starEpochYears = (jd - 2457388.5) / 365.25;
  const starShellPx = Math.max(w, h) * .76;
  globeStarCatalog.forEach(star => {
    const dec = (Number(star.dec) + Number(star.pmdec) * starEpochYears / 3600000) * rad;
    const cosDec = Math.cos(dec);
    const ra = (Number(star.ra) + Number(star.pmra) * starEpochYears / (3600000 * Math.max(.01, Math.abs(cosDec)))) * rad - gmst;
    const dir = [cosDec * Math.cos(ra), cosDec * Math.sin(ra), Math.sin(dec)];
    const local = [dir[0] * east[0] + dir[1] * east[1] + dir[2] * east[2], dir[0] * north[0] + dir[1] * north[1] + dir[2] * north[2], dir[0] * forward[0] + dir[1] * forward[1] + dir[2] * forward[2]];
    const p = project(local.map(value => value * starShellPx / earthR));
    if (p.z >= 0) return;
    const magnitude = Number(star.phot_g_mean_mag);
    const radius = Math.max(.45, Math.min(1.65, 1.45 - magnitude * .12));
    const alpha = Math.max(.12, Math.min(.48, .62 - magnitude * .075));
    ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(153, 213, 176, ${alpha})`; ctx.fill();
  });
  const colors = { GPS: '#00ff9f', Galileo: '#54c7ff', GLONASS: '#ffbf00', BeiDou: '#ff718d', QZSS: '#c694ff', SBAS: '#d6e64a', NavIC: '#ff9254', IMES: '#a5b4fc' };
  const constellation = sat => String(sat.id || 'Unknown').replace(/\s+\S+$/, '');
  const shellKm = { GPS: 20200, Galileo: 23222, GLONASS: 19100, BeiDou: 21528, QZSS: 35786, SBAS: 35786, NavIC: 35786, IMES: 0 };
  const visible = (satellites || []).filter(s => s.azimuth !== null && s.elevation !== null && s.azimuth !== undefined && s.elevation !== undefined && Number.isFinite(Number(s.azimuth)) && Number.isFinite(Number(s.elevation)) && Number(s.elevation) >= 0);
  const positioned = hasFix ? visible : [];
  const summary = document.getElementById('orbit-summary');
  summary.textContent = hasFix
    ? `${visible.length} satellites · view centered on receiver · ${lat.toFixed(4)}°, ${lon.toFixed(4)}°`
    : `${visible.length} satellites · waiting for a valid receiver position`;
  const key = document.getElementById('orbit-key');
  key.replaceChildren();
  [...new Set(visible.map(constellation))].sort().forEach(name => {
    const item = document.createElement('span');
    const dot = document.createElement('i'); dot.style.background = colors[name] || '#d3ddd7';
    item.append(dot, document.createTextNode(`${name} · ${shellKm[name] ? `${(shellKm[name] / 1000).toFixed(1)}k km` : 'orbit n/a'}`));
    key.appendChild(item);
  });

  const shellRadius = km => earthR * (1 + .72 * Math.log1p(km / 6371) / Math.log1p(35786 / 6371));
  ctx.save();
  ctx.beginPath(); ctx.arc(cx, cy, earthR, 0, Math.PI * 2); ctx.clip();
  const ocean = ctx.createRadialGradient(cx - earthR * .35, cy - earthR * .4, earthR * .05, cx, cy, earthR * 1.25);
  ocean.addColorStop(0, '#164534'); ocean.addColorStop(.72, '#0b2b21'); ocean.addColorStop(1, '#06130f');
  ctx.fillStyle = ocean; ctx.fillRect(cx - earthR, cy - earthR, earthR * 2, earthR * 2);
  // Equirectangular graticule projected orthographically, with the receiver at the center.
  ctx.strokeStyle = 'rgba(111, 180, 143, .27)'; ctx.lineWidth = 1;
  for (let latDeg = -60; latDeg <= 60; latDeg += 30) {
    for (const frontSide of [false, true]) {
      ctx.beginPath(); let started = false;
      for (let lonDeg = -180; lonDeg <= 180; lonDeg += 3) {
        const a = latDeg * Math.PI / 180, b = lonDeg * Math.PI / 180;
        const v = [Math.cos(a) * Math.cos(b), Math.cos(a) * Math.sin(b), Math.sin(a)];
        const p = project([v[0] * east[0] + v[1] * east[1] + v[2] * east[2], v[0] * north[0] + v[1] * north[1] + v[2] * north[2], v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2]]);
        const onFront = p.z >= 0;
        if (onFront !== frontSide) { started = false; continue; }
        if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y);
      }
      ctx.strokeStyle = frontSide ? 'rgba(111, 180, 143, .34)' : 'rgba(111, 180, 143, .18)';
      ctx.setLineDash(frontSide ? [] : [2, 4]); ctx.stroke(); ctx.setLineDash([]);
    }
  }
  for (let lonDeg = -180; lonDeg < 180; lonDeg += 30) {
    for (const frontSide of [false, true]) {
      ctx.beginPath(); let started = false;
      for (let latDeg = -90; latDeg <= 90; latDeg += 3) {
        const a = latDeg * Math.PI / 180, b = lonDeg * Math.PI / 180;
        const v = [Math.cos(a) * Math.cos(b), Math.cos(a) * Math.sin(b), Math.sin(a)];
        const p = project([v[0] * east[0] + v[1] * east[1] + v[2] * east[2], v[0] * north[0] + v[1] * north[1] + v[2] * north[2], v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2]]);
        const onFront = p.z >= 0;
        if (onFront !== frontSide) { started = false; continue; }
        if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y);
      }
      ctx.strokeStyle = frontSide ? 'rgba(111, 180, 143, .34)' : 'rgba(111, 180, 143, .18)';
      ctx.setLineDash(frontSide ? [] : [2, 4]); ctx.stroke(); ctx.setLineDash([]);
    }
  }
  // Draw detailed Natural Earth coastlines, sampling edges smoothly at the horizon.
  const continentOutlines = globeLandRings;
  ctx.strokeStyle = 'rgba(119, 190, 148, .78)'; ctx.lineWidth = 1.4; ctx.setLineDash([]);
  continentOutlines.forEach(outline => {
    ctx.beginPath();
    let started = false;
    const projectCoastPoint = (lonDeg, latDeg) => {
      const a = latDeg * Math.PI / 180, b = lonDeg * Math.PI / 180;
      const v = [Math.cos(a) * Math.cos(b), Math.cos(a) * Math.sin(b), Math.sin(a)];
      return project([v[0] * east[0] + v[1] * east[1] + v[2] * east[2], v[0] * north[0] + v[1] * north[1] + v[2] * north[2], v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2]]);
    };
    for (let index = 1; index < outline.length; index += 1) {
      const [lonA, latA] = outline[index - 1], [lonB, latB] = outline[index];
      const coastLonDistance = Math.abs(lonB - lonA) * Math.abs(Math.cos((latA + latB) * Math.PI / 360));
      const steps = Math.max(1, Math.ceil(Math.max(coastLonDistance, Math.abs(latB - latA)) / 2));
      let previous = null;
      for (let step = 0; step <= steps; step += 1) {
        const t = step / steps;
        const lon = lonA + (lonB - lonA) * t, lat = latA + (latB - latA) * t;
        const p = projectCoastPoint(lon, lat);
        if (previous && (previous.p.z >= 0) !== (p.z >= 0)) {
          let low = previous.t, high = t;
          for (let iteration = 0; iteration < 12; iteration += 1) {
            const middle = (low + high) / 2;
            const probe = projectCoastPoint(lonA + (lonB - lonA) * middle, latA + (latB - latA) * middle);
            if ((probe.z >= 0) === (previous.p.z >= 0)) low = middle; else high = middle;
          }
          const edge = projectCoastPoint(lonA + (lonB - lonA) * ((low + high) / 2), latA + (latB - latA) * ((low + high) / 2));
          if (previous.p.z >= 0) { if (started) ctx.lineTo(edge.x, edge.y); started = false; }
          else { ctx.moveTo(edge.x, edge.y); started = true; }
        }
        if (p.z < 0) { started = false; previous = { t, p }; continue; }
        if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y);
        previous = { t, p };
      }
    }
    ctx.stroke();
  });
  ctx.restore();
  ctx.beginPath(); ctx.arc(cx, cy, earthR, 0, Math.PI * 2); ctx.strokeStyle = '#347354'; ctx.lineWidth = 1.5; ctx.stroke();

  const receiverPoint = project([0, 0, 1]);
  if (hasFix) {
    if (baseStationOrbitIcon.complete && baseStationOrbitIcon.naturalWidth) {
      ctx.drawImage(baseStationOrbitIcon, receiverPoint.x - 16, receiverPoint.y - 16, 32, 32);
    }
  }
  const points = [];
  positioned.forEach(sat => {
    const az = Number(sat.azimuth) * Math.PI / 180, el = Number(sat.elevation) * Math.PI / 180;
    const ray = [Math.cos(el) * Math.sin(az) * east[0] + Math.cos(el) * Math.cos(az) * north[0] + Math.sin(el) * forward[0],
      Math.cos(el) * Math.sin(az) * east[1] + Math.cos(el) * Math.cos(az) * north[1] + Math.sin(el) * forward[1],
      Math.cos(el) * Math.sin(az) * east[2] + Math.cos(el) * Math.cos(az) * north[2] + Math.sin(el) * forward[2]];
    const name = constellation(sat), altitude = shellKm[name] || 20200;
    // Solve the line/sphere intersection for the nominal orbital radius.
    const r0 = 6371, orbitalR = r0 + altitude;
    const dot = ray[0] * forward[0] + ray[1] * forward[1] + ray[2] * forward[2];
    const discriminant = Math.max(0, (r0 * dot) ** 2 + orbitalR ** 2 - r0 ** 2);
    const distance = -r0 * dot + Math.sqrt(discriminant);
    const actual = [forward[0] * r0 + ray[0] * distance, forward[1] * r0 + ray[1] * distance, forward[2] * r0 + ray[2] * distance];
    const actualR = Math.hypot(...actual), shownR = shellRadius(altitude) / earthR;
    const scaled = actual.map(v => v * shownR / actualR);
    const model = [scaled[0] * east[0] + scaled[1] * east[1] + scaled[2] * east[2], scaled[0] * north[0] + scaled[1] * north[1] + scaled[2] * north[2], scaled[0] * forward[0] + scaled[1] * forward[1] + scaled[2] * forward[2]];
    const p = project(model);
    points.push({ ...p, model, sat, name, color: colors[name] || '#d3ddd7', altitude, az: Number(sat.azimuth), el: Number(sat.elevation), signal: sat.signal });
  });
  // Show the constellation through the globe, while coastlines above remain
  // limited to the front-facing hemisphere.
  orbitPoints = points;
  const now = Date.now();
  if (sampleTrails) {
    points.forEach(point => {
      const history = orbitTrailHistory.get(point.sat.id) || [];
      history.push({ model: point.model, time: now });
      while (history.length && (history.length > 48 || now - history[0].time > 192000)) history.shift();
      orbitTrailHistory.set(point.sat.id, history);
    });
  }
  orbitPoints.forEach(point => {
    const history = orbitTrailHistory.get(point.sat.id) || [];
    if (history.length < 2) return;
    for (let index = 1; index < history.length; index += 1) {
      const from = project(history[index - 1].model), to = project(history[index].model);
      const visible = p => {
        const dx = (p.x - cx) / earthR, dy = (p.y - cy) / earthR;
        return dx * dx + dy * dy > 1 || p.z >= Math.sqrt(Math.max(0, 1 - dx * dx - dy * dy));
      };
      if (!visible(from) || !visible(to)) continue;
      ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y);
      ctx.strokeStyle = point.color; ctx.globalAlpha = .08 + .24 * index / (history.length - 1); ctx.lineWidth = 1.5; ctx.stroke();
    }
    ctx.globalAlpha = 1;
  });
  orbitPoints.sort((a, b) => a.z - b.z).forEach(point => {
    const { x, y, color } = point;
    const receiver = project([0, 0, 1]);
    ctx.beginPath(); ctx.moveTo(receiver.x, receiver.y); ctx.lineTo(x, y); ctx.strokeStyle = color; ctx.globalAlpha = .22; ctx.lineWidth = 1; ctx.stroke(); ctx.globalAlpha = 1;
    const icon = orbitIcons[point.name];
    if (icon?.complete && icon.naturalWidth) ctx.drawImage(icon, x - 15, y - 15, 30, 30);
    else { ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill(); }
  });
  ctx.textAlign = 'left';
}
const orbitCanvas = document.getElementById('orbit-view');
new ResizeObserver(() => drawOrbitView()).observe(orbitCanvas);
window.addEventListener('resize', () => drawOrbitView());
const orbitTooltip = document.getElementById('orbit-tooltip');
function showOrbitTooltip(point, clientX, clientY) {
  const card = document.getElementById('orbit-card');
  const cardRect = card.getBoundingClientRect();
  const signal = point.signal === null || point.signal === undefined ? NaN : Number(point.signal);
  const country = ({ GPS: 'United States', Galileo: 'European Union', GLONASS: 'Russia', BeiDou: 'China', QZSS: 'Japan', NavIC: 'India', IMES: 'Japan', SBAS: 'Regional system (multiple countries)' })[point.name] || 'Unknown';
  orbitTooltip.replaceChildren();
  const title = document.createElement('strong'); title.textContent = point.sat.id;
  const lines = [
    `${point.name} · approx. ${(point.altitude / 1000).toFixed(1)}k km orbit`,
    `Country of origin: ${country}`,
    `Az ${point.az.toFixed(1)}° · El ${point.el.toFixed(1)}°`,
    point.sat.used ? 'Used in current fix' : 'Visible · not used in fix'
  ];
  orbitTooltip.append(title, ...lines.map(line => { const row = document.createElement('div'); row.textContent = line; return row; }));
  const signalRow = document.createElement('div'); signalRow.className = 'orbit-tooltip-signal';
  const signalLabel = document.createElement('span'); signalLabel.textContent = 'Signal';
  const signalBars = document.createElement('div');
  const signalClassName = !Number.isFinite(signal) ? '' : signal < 20 ? 'signal-weak' : signal < 30 ? 'signal-fair' : signal < 40 ? 'signal-good' : 'signal-strong';
  signalBars.className = `sat-cell ${signalClassName}`; signalBars.setAttribute('aria-hidden', 'true');
  const strength = Number.isFinite(signal) ? Math.max(0, Math.min(4, Math.ceil(signal / 10))) : 0;
  for (let index = 1; index <= 4; index += 1) {
    const bar = document.createElement('i'); if (index <= strength) bar.className = 'on'; signalBars.appendChild(bar);
  }
  const signalValue = document.createElement('span'); signalValue.textContent = Number.isFinite(signal) ? `${signal.toFixed(1)} dB-Hz` : 'unavailable';
  signalRow.append(signalLabel, signalBars, signalValue); orbitTooltip.appendChild(signalRow);
  orbitTooltip.style.display = 'block';
  const x = clientX - cardRect.left, y = clientY - cardRect.top;
  const left = Math.max(8, Math.min(card.clientWidth - orbitTooltip.offsetWidth - 8, x + 14));
  const top = Math.max(52, Math.min(card.clientHeight - orbitTooltip.offsetHeight - 40, y - orbitTooltip.offsetHeight / 2));
  orbitTooltip.style.left = `${left}px`; orbitTooltip.style.top = `${top}px`;
}
orbitCanvas.addEventListener('pointerdown', event => {
  if (event.button !== 0 && event.pointerType === 'mouse') return;
  orbitDrag = { x: event.clientX, y: event.clientY };
  orbitCanvas.classList.add('dragging'); orbitTooltip.style.display = 'none';
  orbitCanvas.setPointerCapture(event.pointerId); event.preventDefault();
});
orbitCanvas.addEventListener('pointermove', event => {
  if (orbitDrag) {
    const dx = event.clientX - orbitDrag.x, dy = event.clientY - orbitDrag.y;
    orbitDrag = { x: event.clientX, y: event.clientY };
    orbitRotation.yaw -= dx * .008;
    orbitRotation.pitch = Math.max(-1.35, Math.min(1.35, orbitRotation.pitch + dy * .008));
    drawOrbitView(); return;
  }
  const rect = orbitCanvas.getBoundingClientRect();
  const x = event.clientX - rect.left, y = event.clientY - rect.top;
  const point = [...orbitPoints].reverse().find(p => Math.hypot(p.x - x, p.y - y) < 16);
  if (point) showOrbitTooltip(point, event.clientX, event.clientY); else orbitTooltip.style.display = 'none';
});
function stopOrbitDrag() { orbitDrag = null; orbitCanvas.classList.remove('dragging'); }
orbitCanvas.addEventListener('pointerup', stopOrbitDrag);
orbitCanvas.addEventListener('pointercancel', stopOrbitDrag);
orbitCanvas.addEventListener('pointerleave', () => { if (!orbitDrag) orbitTooltip.style.display = 'none'; });
orbitCanvas.addEventListener('wheel', event => {
  event.preventDefault();
  orbitZoom = Math.max(.65, Math.min(2.2, orbitZoom * Math.exp(-event.deltaY * .001)));
  drawOrbitView();
}, { passive: false });

async function refresh() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();

    document.getElementById('clock').textContent = d.time;
    document.getElementById('version').textContent = d.version;
    document.getElementById('hostname').textContent = d.hostname;
    document.getElementById('local-hostname').textContent = d.local_hostname;
    document.getElementById('uptime').textContent = d.uptime;
    document.getElementById('temp').textContent = d.temp;
    document.getElementById('ip').textContent = d.ip;

    document.getElementById('cpu').textContent = d.cpu + ' %';
    document.getElementById('cpu-bar').style.width = d.cpu + '%';
    document.getElementById('mem').textContent = d.mem;
    document.getElementById('mem-bar').style.width = d.mem_pct + '%';
    document.getElementById('disk').textContent = d.disk;
    document.getElementById('disk-bar').style.width = d.disk_pct + '%';
    document.getElementById('load').textContent = d.load;
    document.getElementById('rtcm-port').textContent = `TCP :${d.rtcm_port}`;
    document.getElementById('rtcm-clients').textContent = d.rtcm_clients;
    document.getElementById('str-restarts').textContent = d.str_restarts;
    document.getElementById('stream-uptime').textContent = d.stream_uptime;
    document.getElementById('wifi-interface').textContent = d.wifi.interface;
    const ethernet = d.ethernet || [];
    document.querySelector('.ethernet-icon').classList.toggle('active', ethernet.length > 0);
    document.getElementById('ethernet-status').textContent = ethernet.length
      ? ethernet.map(item => `${item.interface}${item.addresses.length ? ` (${item.addresses.join(', ')})` : ''}`).join(', ')
      : 'No active Ethernet connection';
    document.getElementById('wifi-ssid').textContent = d.wifi.ssid;
    const wifiDbm = Number(d.wifi.dbm);
    const hasWifiSignal = d.wifi.dbm !== null && Number.isFinite(wifiDbm);
    const wifiThresholds = [-30, -60, -70, -80];
    const activeWifiBars = hasWifiSignal ? wifiThresholds.filter(threshold => wifiDbm >= threshold).length : 0;
    const wifiColorClass = !hasWifiSignal ? 'signal-none' : activeWifiBars <= 1 ? 'signal-weak' : activeWifiBars === 2 ? 'signal-fair' : activeWifiBars === 3 ? 'signal-good' : 'signal-strong';
    const wifiSignal = document.getElementById('wifi-signal');
    wifiSignal.textContent = d.wifi.signal;
    wifiSignal.className = wifiColorClass;
    document.querySelector('.wifi-icon').setAttribute('class', `wifi-icon ${wifiColorClass}`);
    document.querySelectorAll('.wifi-segment').forEach((segment, index) => {
      segment.classList.toggle('active', hasWifiSignal && wifiDbm >= wifiThresholds[index]);
    });
    document.getElementById('wifi-link').textContent = d.wifi.link;
    document.getElementById('wifi-frequency').textContent = d.wifi.frequency || '—';
    document.getElementById('wifi-bitrate').textContent = d.wifi.bitrate || '—';
    document.getElementById('net-traffic').textContent = `${d.network_traffic.received} / ${d.network_traffic.sent} (${d.network_traffic.interface})`;
    updateTrafficPanel(d.network_traffic, d.rtcm_clients);

    const st = document.getElementById('str-status');
    st.textContent = d.str_status.toUpperCase();
    st.className = 'status ' + (d.str_status === 'active' ? 'ok' : 'fail');
    document.getElementById('str-log').textContent = d.str_log || 'No recent logs';

    document.getElementById('network').textContent = d.network || '–';
    document.getElementById('ports').textContent = d.ports || 'No RTK ports listening';
    document.getElementById('usb').textContent = d.usb;
    document.getElementById('serial').textContent = d.serial;
    document.getElementById('gps-source').textContent = d.gps.source;
    document.getElementById('gps-fix').textContent = d.gps.fix;
    document.getElementById('gps-position').textContent = d.gps.position;
    document.getElementById('gps-altitude').textContent = d.gps.altitude;
    document.getElementById('gps-speed').textContent = d.gps.speed;
    document.getElementById('gps-satellites').textContent = d.gps.satellites;
    document.getElementById('gps-accuracy').textContent = d.gps.accuracy;
    document.getElementById('gps-dop').textContent = `${d.gps.hdop} / ${d.gps.pdop}`;
    document.getElementById('gps-fix-time').textContent = d.gps.fix_time;
    document.getElementById('gps-satellite-detail').textContent = d.gps.satellite_detail || 'No satellite details';
    document.getElementById('satellite-status').textContent = d.gps.satellite_status;
    updateGpsMap(d.gps);
    updateSatelliteGraphics(d.gps.satellite_data);
    orbitGps = d.gps;
    orbitSatellites = d.gps.satellite_data || [];
    drawOrbitView(orbitGps, orbitSatellites, true);
    document.getElementById('active-mode').textContent = d.mode === 'telemetry' ? 'GPS telemetry' : d.mode === 'corrections' ? 'RTCM corrections' : 'Stopped';
    document.getElementById('corrections-mode').classList.toggle('active', d.mode === 'corrections');
    document.getElementById('telemetry-mode').classList.toggle('active', d.mode === 'telemetry');
    const updateStatus = d.update_status || 'Ready to update.';
    document.getElementById('action-message').textContent = updateStatus;
    document.getElementById('update-button').disabled = updateStatus.startsWith('Starting RTK-Base update') || updateStatus.startsWith('Updating RTK-Base') || updateStatus.startsWith('APT upgrade available:');
  } catch (e) {
    console.error(e);
  }
}
async function setMode(mode) {
  const buttons = document.querySelectorAll('.mode-controls button');
  buttons.forEach(button => button.disabled = true);
  const message = document.getElementById('mode-message');
  message.textContent = 'Switching mode…';
  try {
    const response = await fetch('/api/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Mode switch failed');
    message.textContent = mode === 'telemetry'
      ? 'GPS telemetry active. RTCM corrections are paused.'
      : 'RTCM corrections active. GPS telemetry is paused.';
    await refresh();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
}
async function rebootPi() {
  if (!window.confirm('Reboot the Raspberry Pi now? The dashboard and RTCM stream will be unavailable briefly.')) return;
  const button = document.getElementById('reboot-button');
  const message = document.getElementById('action-message');
  button.disabled = true;
  message.textContent = 'Sending reboot command...';
  try {
    const response = await fetch('/api/reboot', { method: 'POST' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Reboot failed');
    message.textContent = 'Rebooting Pi...';
  } catch (error) {
    message.textContent = error.message;
    button.disabled = false;
  }
}
async function updatePi() {
  if (!window.confirm('Update RTK-Base now? This discards tracked local changes, pulls the latest repository version, and reruns setup.')) return;
  const button = document.getElementById('update-button');
  button.disabled = true;
  updateOutputOffset = 0;
  updateUpgradePromptShown = false;
  document.getElementById('update-terminal-output').textContent = '';
  document.getElementById('update-terminal-status').textContent = 'Starting update...';
  document.getElementById('update-terminal-screen').classList.add('active');
  if (updatePollTimer) window.clearTimeout(updatePollTimer);
  if (updateReturnTimer) window.clearTimeout(updateReturnTimer);
  try {
    const response = await fetch('/api/update', { method: 'POST' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Update failed to start');
    document.getElementById('update-terminal-status').textContent = 'Running update script...';
    pollUpdateOutput();
  } catch (error) {
    document.getElementById('update-terminal-output').textContent = `${error.message}\n`;
    document.getElementById('update-terminal-status').textContent = 'Could not start update.';
    updateReturnTimer = window.setTimeout(closeUpdateTerminal, 2500);
  }
}
async function openFileDialog() {
  const backdrop = document.getElementById('file-dialog-backdrop');
  const list = document.getElementById('file-download-list');
  const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
  const bodyPaddingRight = parseFloat(getComputedStyle(document.body).paddingRight) || 0;
  document.body.style.paddingRight = `${bodyPaddingRight + scrollbarWidth}px`;
  backdrop.hidden = false;
  document.body.style.overflow = 'hidden';
  document.getElementById('file-dialog-message').textContent = '';
  list.textContent = 'Loading available files...';
  document.querySelector('.file-dialog-close').focus();
  try {
    const response = await fetch('/api/downloads');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not list files');
    renderDownloadItems(result.files);
  } catch (error) {
    list.textContent = error.message;
  }
}
async function loadRepoFiles() {
  const button = document.getElementById('repo-refresh-button');
  const status = document.getElementById('repo-file-status');
  button.disabled = true;
  status.textContent = 'Reading repository tree...';
  try {
    const response = await fetch('/api/repo-files', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not read repository files');
    document.getElementById('repo-tree').textContent = result.tree || '(Repository is empty)';
    const associations = document.getElementById('repo-associations');
    associations.replaceChildren();
    result.associations.forEach(item => {
      const row = document.createElement('div');
      row.className = 'repo-association';
      const source = document.createElement('strong');
      source.textContent = item.source;
      const state = item.generated ? 'generated' : item.installed ? 'installed' : 'not installed';
      row.append(source, document.createTextNode(` → ${item.target} (${state})`));
      associations.appendChild(row);
    });
    status.textContent = `${result.file_count} tracked files · ${result.root}`;
  } catch (error) {
    document.getElementById('repo-tree').textContent = 'Repository tree is unavailable.';
    document.getElementById('repo-associations').replaceChildren();
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
function closeFileDialog() {
  document.getElementById('file-dialog-backdrop').hidden = true;
  document.body.style.overflow = '';
  document.body.style.paddingRight = '';
  document.getElementById('files-button').focus();
}
async function openReadmeDialog() {
  const backdrop = document.getElementById('readme-dialog-backdrop');
  const content = document.getElementById('readme-content');
  const message = document.getElementById('readme-dialog-message');
  const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
  const bodyPaddingRight = parseFloat(getComputedStyle(document.body).paddingRight) || 0;
  document.body.style.paddingRight = `${bodyPaddingRight + scrollbarWidth}px`;
  backdrop.hidden = false;
  document.body.style.overflow = 'hidden';
  content.textContent = 'Loading README...'; message.textContent = '';
  try {
    const response = await fetch('/api/readme', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not load README');
    renderReadme(result.content, content);
  } catch (error) {
    content.textContent = 'README is unavailable.';
    message.textContent = error.message;
  }
  document.querySelector('#readme-dialog-backdrop .file-dialog-close')?.focus();
}
async function openLicenseDialog() {
  const backdrop = document.getElementById('license-dialog-backdrop');
  const content = document.getElementById('license-content');
  const message = document.getElementById('license-dialog-message');
  const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
  const bodyPaddingRight = parseFloat(getComputedStyle(document.body).paddingRight) || 0;
  document.body.style.paddingRight = `${bodyPaddingRight + scrollbarWidth}px`;
  backdrop.hidden = false;
  document.body.style.overflow = 'hidden';
  content.textContent = 'Loading licence...'; message.textContent = '';
  try {
    const response = await fetch('/api/license', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not load licence');
    content.textContent = result.content;
  } catch (error) {
    content.textContent = 'Licence is unavailable.';
    message.textContent = error.message;
  }
  document.querySelector('#license-dialog-backdrop .file-dialog-close')?.focus();
}
function escapeReadmeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}
function readmeInline(value) {
  const icons = [];
  const withIconTokens = String(value).replace(/<img\b([^>]*)>/gi, (tag, attributes) => {
    const source = attributes.match(/\bsrc="(dashboard\/static\/icons\/[\w.-]+\.svg)"/i)?.[1];
    const alt = attributes.match(/\balt="([^"]*)"/i)?.[1];
    const width = attributes.match(/\bwidth="(\d+)"/i)?.[1];
    const height = attributes.match(/\bheight="(\d+)"/i)?.[1];
    if (!source || alt === undefined || !width || !height) return tag;
    const token = `READMEICON${icons.length}TOKEN`;
    icons.push(`<img src="/static/icons/${source.split('/').pop()}" alt="${escapeReadmeHtml(alt)}" width="${width}" height="${height}">`);
    return token;
  });
  let html = escapeReadmeHtml(withIconTokens);
  html = html.replace(/READMEICON(\d+)TOKEN/g, (token, index) => icons[Number(index)] || token);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|#[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html;
}
function renderReadme(markdown, target) {
  const lines = String(markdown).split(/\r?\n/);
  const blocks = [];
  const isTableDivider = line => /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line.trim());
  const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }
    if (line === '<p align="center">') { blocks.push('<div class="readme-center">'); index += 1; continue; }
    if (line === '</p>') { blocks.push('</div>'); index += 1; continue; }
    const image = line.match(/^<img\b[^>]*\bsrc="dashboard\/static\/icons\/[\w.-]+\.svg"[^>]*>$/);
    if (image) { blocks.push(readmeInline(line)); index += 1; continue; }
    const centeredHeading = line.match(/^<h1 align="center">(.*?)<\/h1>$/);
    if (centeredHeading) { blocks.push(`<h1 class="readme-center">${escapeReadmeHtml(centeredHeading[1])}</h1>`); index += 1; continue; }
    const centeredParagraph = line.match(/^<p align="center">(.*?)<\/p>$/);
    if (centeredParagraph) {
      const bold = centeredParagraph[1].match(/^<strong>(.*?)<\/strong>$/);
      const content = bold ? `<strong>${escapeReadmeHtml(bold[1])}</strong>` : readmeInline(centeredParagraph[1]);
      blocks.push(`<p class="readme-center">${content}</p>`); index += 1; continue;
    }
    const fence = line.match(/^```(.*)$/);
    if (fence) {
      const code = []; index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) code.push(lines[index++]);
      index += 1;
      blocks.push(`<pre><code>${escapeReadmeHtml(code.join('\n'))}</code></pre>`); continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) { const level = heading[1].length; blocks.push(`<h${level}>${readmeInline(heading[2])}</h${level}>`); index += 1; continue; }
    if (line.startsWith('|') && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const header = cells(line); index += 2;
      const rows = [];
      while (index < lines.length && lines[index].trim().startsWith('|')) rows.push(cells(lines[index++]));
      blocks.push(`<table><thead><tr>${header.map(cell => `<th>${readmeInline(cell)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${readmeInline(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    const listMatch = line.match(/^(?:[-*]|\d+\.)\s+(.+)$/);
    if (listMatch) {
      const ordered = /^\d+\./.test(line), tag = ordered ? 'ol' : 'ul', items = [];
      while (index < lines.length) {
        const item = lines[index].trim().match(/^(?:[-*]|\d+\.)\s+(.+)$/);
        if (!item || (/^\d+\./.test(lines[index].trim())) !== ordered) break;
        const itemLines = [item[1]]; index += 1;
        while (index < lines.length && /^\s{2,}\S/.test(lines[index])) itemLines.push(lines[index++].trim());
        items.push(`<li>${readmeInline(itemLines.join(' '))}</li>`);
      }
      blocks.push(`<${tag}>${items.join('')}</${tag}>`); continue;
    }
    const paragraph = [line]; index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,3}\s|```|\||[-*]\s|\d+\.\s|<p align=|<h1 align=|<img )/.test(lines[index].trim())) paragraph.push(lines[index++].trim());
    blocks.push(`<p>${readmeInline(paragraph.join(' '))}</p>`);
  }
  target.innerHTML = blocks.join('\n');
}
function closeReadmeDialog() {
  document.getElementById('readme-dialog-backdrop').hidden = true;
  document.body.style.overflow = '';
  document.body.style.paddingRight = '';
  document.getElementById('readme-button').focus();
}
function closeLicenseDialog() {
  document.getElementById('license-dialog-backdrop').hidden = true;
  document.body.style.overflow = '';
  document.body.style.paddingRight = '';
  document.getElementById('license-button').focus();
}
function handleLicenseDialogBackdrop(event) {
  if (event.target.id === 'license-dialog-backdrop') closeLicenseDialog();
}
function handleReadmeDialogBackdrop(event) {
  if (event.target.id === 'readme-dialog-backdrop') closeReadmeDialog();
}
function handleFileDialogBackdrop(event) {
  if (event.target.id === 'file-dialog-backdrop') closeFileDialog();
}
function renderDownloadItems(items) {
  const list = document.getElementById('file-download-list');
  list.replaceChildren();
  const categories = new Map();
  items.forEach(item => {
    if (!categories.has(item.category)) categories.set(item.category, []);
    categories.get(item.category).push(item);
  });
  categories.forEach((categoryItems, category) => {
    const heading = document.createElement('h3');
    heading.className = 'file-category';
    heading.textContent = category;
    list.appendChild(heading);
    categoryItems.forEach(item => {
      const row = document.createElement('div');
      row.className = 'file-item';
      const details = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'file-item-name';
      name.textContent = item.name;
      const description = document.createElement('div');
      description.className = 'file-item-description';
      description.textContent = `${item.description} · ${item.filename}`;
      details.append(name, description);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'file-download-button';
      button.setAttribute('aria-label', `Download ${item.name}`);
      const icon = document.createElement('img');
      icon.src = DOWNLOAD_ICON_URL;
      icon.alt = '';
      icon.setAttribute('aria-hidden', 'true');
      const label = document.createElement('span');
      label.textContent = 'Download';
      button.append(icon, label);
      button.addEventListener('click', () => downloadFile(item, button));
      row.append(details, button);
      list.appendChild(row);
    });
  });
}
async function downloadFile(item, button) {
  const message = document.getElementById('file-dialog-message');
  message.textContent = `Preparing ${item.filename}...`;
  button.disabled = true;
  try {
    const response = await fetch(`/api/downloads/${encodeURIComponent(item.id)}`);
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || `Could not download ${item.filename}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = item.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    message.textContent = `Downloaded ${item.filename}.`;
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !document.getElementById('file-dialog-backdrop').hidden) closeFileDialog();
  if (event.key === 'Escape' && !document.getElementById('readme-dialog-backdrop').hidden) closeReadmeDialog();
  if (event.key === 'Escape' && !document.getElementById('license-dialog-backdrop').hidden) closeLicenseDialog();
});
function closeUpdateTerminal() {
  document.getElementById('update-terminal-screen').classList.remove('active');
  document.getElementById('update-button').disabled = false;
  if (updatePollTimer) window.clearTimeout(updatePollTimer);
  updatePollTimer = null;
}
async function pollUpdateOutput() {
  try {
    const response = await fetch(`/api/update/output?offset=${updateOutputOffset}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Update output endpoint unavailable');
    const result = await response.json();
    if (result.output) {
      const output = document.getElementById('update-terminal-output');
      output.textContent += result.output;
      output.scrollTop = output.scrollHeight;
    }
    updateOutputOffset = result.offset;
    document.getElementById('update-terminal-status').textContent = result.status;
    if (result.status.startsWith('APT upgrade available:') && !updateUpgradePromptShown) {
      updateUpgradePromptShown = true;
      const packageCount = result.status.match(/APT upgrade available: (\d+)/)?.[1] || 'some';
      document.getElementById('apt-upgrade-message').textContent = `${packageCount} system package(s) can be upgraded. Upgrade output will appear in this progress terminal.`;
      document.getElementById('apt-upgrade-dialog-backdrop').hidden = false;
    }
    if (result.done) {
      updateReturnTimer = window.setTimeout(() => {
        closeUpdateTerminal();
        if (result.success) window.location.reload();
      }, 2200);
      return;
    }
  } catch (error) {
    document.getElementById('update-terminal-status').textContent = 'Dashboard restarting or reconnecting...';
  }
  updatePollTimer = window.setTimeout(pollUpdateOutput, 800);
}
async function respondToAptUpgrade(approve) {
  const buttons = document.querySelectorAll('.apt-upgrade-actions button');
  buttons.forEach(button => button.disabled = true);
  try {
    const response = await fetch('/api/update/apt-upgrade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not submit the system upgrade choice');
    document.getElementById('apt-upgrade-dialog-backdrop').hidden = true;
    document.getElementById('update-terminal-status').textContent = approve
      ? 'Starting system package upgrade...'
      : 'Continuing without system package upgrades...';
  } catch (error) {
    document.getElementById('apt-upgrade-message').textContent = error.message;
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
}
setupCollapsiblePanels();
refresh();
loadRepoFiles();
setInterval(refresh, 4000);
