import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { ViewportGizmo } from 'three-viewport-gizmo';

// --- Types ---

interface Node { tag: number; coords: number[]; }
interface Element { tag: number; type: string; nodes: number[]; section?: number; }
interface Support { tag: number; dofs: number[]; }
interface NodalLoad { tag: number; values: number[]; }
interface NodeResult { tag: number; disp: number[]; reaction: number[]; }
interface SectionForces {
    x: number[];
    N: number[];
    V?: number[];
    M?: number[];
    Vz?: number[];
    T?: number[];
    My?: number[];
    Mz?: number[];
}
interface ElementResult { tag: number; local_forces: number[]; section_forces: SectionForces; }

interface AnalysisData {
    converged: boolean;
    node_results: NodeResult[];
    element_results: ElementResult[];
}

interface Section {
    tag?: number;
    color?: string;
    label?: string;
}

interface Viewer {
    sections?: Section[];
    precision?: number;
}

interface ModelData {
    schema_version: number;
    ndm: number;
    ndf: number;
    nodes: Node[];
    elements: Element[];
    supports: Support[];
    nodal_loads: NodalLoad[];
    viewer?: Viewer;
    error: string | null;
    analysis?: AnalysisData;
}

type IncomingMessage =
    | { type: 'modelData'; data: ModelData }
    | { type: 'analysisData'; data: AnalysisData; ndf: number }
    | { type: 'loading' }
    | { type: 'analysisRunning' }
    | { type: 'error'; message: string }
    | { type: 'takeScreenshot' };

// --- Force component definitions per ndf ---

interface ForceComponent { label: string; key: keyof SectionForces; }

function forceComponents(ndf: number): ForceComponent[] {
    if (ndf <= 3) {
        return [
            { label: 'Axial (N)',   key: 'N' },
            { label: 'Shear (V)',   key: 'V' },
            { label: 'Moment (M)',  key: 'M' },
        ];
    }
    return [
        { label: 'Axial (N)',   key: 'N' },
        { label: 'Shear Y',    key: 'V' },
        { label: 'Shear Z',    key: 'Vz' },
        { label: 'Moment X',   key: 'T' },
        { label: 'Moment Y',   key: 'My' },
        { label: 'Moment Z',   key: 'Mz' },
    ];
}

// --- Rainbow colormap (blue → cyan → green → yellow → red) ---

function rainbow(t: number): THREE.Color {
    t = Math.max(0, Math.min(1, t));
    // Hue goes from 240° (blue) down to 0° (red)
    return new THREE.Color().setHSL((1 - t) * 0.667, 1.0, 0.55);
}

// --- VS Code API ---

declare function acquireVsCodeApi(): { postMessage: (msg: unknown) => void };
const vscodeApi = acquireVsCodeApi();

// --- Renderer & scene ---

const canvas = document.getElementById('canvas') as HTMLCanvasElement;
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);

// Lights — added once, never cleared with the model
const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
scene.add(ambientLight);
const sunLight = new THREE.DirectionalLight(0xffffff, 0.9);
sunLight.position.set(5, 10, 8);
scene.add(sunLight);
const fillLight = new THREE.DirectionalLight(0xffffff, 0.25);
fillLight.position.set(-5, -4, -6);
scene.add(fillLight);

let camera: THREE.PerspectiveCamera | THREE.OrthographicCamera = defaultCamera();
let controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

// --- Gizmo ---

let gizmo: ViewportGizmo | null = null;

const modelObjects: THREE.Object3D[] = [];
let lineMaterial: LineMaterial | null = null;

const nodeLabelGroup = new THREE.Group();
const elementLabelGroup = new THREE.Group();
const loadLabelGroup = new THREE.Group();
scene.add(nodeLabelGroup, elementLabelGroup, loadLabelGroup);

// Store last data for re-coloring and inspection
let lastAnalysis: AnalysisData | null = null;
let lastElements: Element[] = [];
let lastNodes: Node[] = [];
let lastNdm: number = 2;
let lastNdf: number = 3;
let lastNodeMap: Map<number, THREE.Vector3> = new Map();
let lastViewer: Viewer | undefined;

// Reverse-lookup arrays: geometry index → structural tag
let nodeTagsByIndex: number[] = [];
let elementTagsBySegment: number[] = [];
const NEP = 11; // evaluation points per element (matches Python default)
let segmentsPerElement: number = NEP - 1;

// Element selection state
let selectedElementTag: number | null = null;
// --- UI ---

const statusEl       = document.getElementById('status') as HTMLSpanElement;
const labelsSelect   = document.getElementById('labels-select') as HTMLSelectElement;
const errorBanner    = document.getElementById('error-banner') as HTMLDivElement;
const runBtn         = document.getElementById('run-btn') as HTMLButtonElement;
const screenshotBtn  = document.getElementById('screenshot-btn') as HTMLButtonElement;
const forceSelector  = document.getElementById('force-selector') as HTMLDivElement;
const forceSelect    = document.getElementById('force-select') as HTMLSelectElement;
const colorbar       = document.getElementById('colorbar') as HTMLDivElement;
const colorbarCanvas = document.getElementById('colorbar-canvas') as HTMLCanvasElement;
const colorbarTitle  = document.getElementById('colorbar-title') as HTMLDivElement;
const colorbarMin    = document.getElementById('colorbar-min') as HTMLSpanElement;
const colorbarMax    = document.getElementById('colorbar-max') as HTMLSpanElement;
const resultsPanel   = document.getElementById('results-panel') as HTMLDivElement;
const resultsToggle  = document.getElementById('results-toggle') as HTMLButtonElement;
const resultsBody    = document.getElementById('results-body') as HTMLDivElement;
const resultsThead   = document.getElementById('results-thead') as HTMLTableSectionElement;
const resultsTbody   = document.getElementById('results-tbody') as HTMLTableSectionElement;
const resultsFilter  = document.getElementById('results-filter') as HTMLInputElement;
const tabBtns        = resultsPanel.querySelectorAll<HTMLButtonElement>('.tab-btn');
let currentTab: 'nodes' | 'elements' = 'nodes';

runBtn.addEventListener('click', () => vscodeApi.postMessage({ type: 'runAnalysis' }));
screenshotBtn.addEventListener('click', () => {
    renderer.render(scene, camera);
    const data = renderer.domElement.toDataURL('image/png');
    vscodeApi.postMessage({ type: 'screenshot', data });
});
labelsSelect.addEventListener('change', () => updateLabelVisibility());

function updateLabelVisibility(): void {
    const v = labelsSelect.value;
    nodeLabelGroup.visible    = v === 'nodes';
    elementLabelGroup.visible = v === 'members';
    loadLabelGroup.visible    = v === 'loads';
}
forceSelect.addEventListener('change', () => {
    if (forceSelect.value === '') {
        restoreDefaultColors(lastElements, lastNodeMap);
    } else if (lastAnalysis) {
        recolorElements(lastElements, lastNodeMap, lastAnalysis);
    }
});

// Results panel: tab switching
tabBtns.forEach(btn => btn.addEventListener('click', () => {
    const tab = btn.dataset.tab as 'nodes' | 'elements';
    if (tab === currentTab) return;
    currentTab = tab;
    resultsFilter.value = '';
    tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    if (lastAnalysis) buildTable();
}));

// Results panel: collapse/expand
resultsToggle.addEventListener('click', () => {
    const collapsed = resultsBody.style.display === 'none';
    resultsBody.style.display = collapsed ? 'block' : 'none';
    resultsToggle.innerHTML = collapsed ? 'Results &#9660;' : 'Results &#9650;';
});

// Results panel: search filter
resultsFilter.addEventListener('input', () => filterTable());

function filterTable(): void {
    const q = resultsFilter.value.toLowerCase().trim();
    const rows = Array.from(resultsTbody.querySelectorAll('tr'));
    for (const row of rows) {
        if (!q) { (row as HTMLElement).style.display = ''; continue; }
        const cells = Array.from(row.querySelectorAll('td'));
        const match = cells.some(td => td.textContent?.trim().toLowerCase().startsWith(q));
        (row as HTMLElement).style.display = match ? '' : 'none';
    }
}

// --- Animate loop ---

function animate(): void {
    requestAnimationFrame(animate);
    controls.update();

    renderer.render(scene, camera);
    gizmo?.render();
}
animate();

// --- Resize ---

window.addEventListener('resize', () => {
    renderer.setSize(window.innerWidth, window.innerHeight);
    if (camera instanceof THREE.PerspectiveCamera) {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
    }
    lineMaterial?.resolution.set(window.innerWidth, window.innerHeight);
    gizmo?.update();
});

// --- Message handler ---

window.addEventListener('message', (event: MessageEvent<IncomingMessage>) => {
    const msg = event.data;
    if (msg.type === 'loading') {
        setStatus('Loading...');
        hideError();
    } else if (msg.type === 'analysisRunning') {
        runBtn.disabled = true;
        runBtn.textContent = 'Running...';
        setStatus('Running analysis...');
    } else if (msg.type === 'error') {
        runBtn.disabled = false;
        runBtn.textContent = '▶ Run Analysis';
        setStatus('Error');
        showError(msg.message);
    } else if (msg.type === 'modelData') {
        hideError();
        runBtn.disabled = false;
        runBtn.textContent = '▶ Run Analysis';
        if (msg.data.error) {
            setStatus('Script error');
            showError(msg.data.error);
        } else {
            render(msg.data);
            setStatus(`${msg.data.nodes.length} nodes · ${msg.data.elements.length} elements`);
        }
    } else if (msg.type === 'analysisData') {
        runBtn.disabled = false;
        runBtn.textContent = '▶ Run Analysis';
        hideError();
        populateForceSelector(msg.ndf);
        forceSelector.style.display = 'block';
        lastAnalysis = msg.data;
        lastNdf = msg.ndf;
        if (forceSelect.value !== '') {
            recolorElements(lastElements, lastNodeMap, msg.data);
        }
        resultsPanel.style.display = 'block';
        buildTable();
        setStatus('Analysis complete');
    } else if (msg.type === 'takeScreenshot') {
        renderer.render(scene, camera);
        const data = renderer.domElement.toDataURL('image/png');
        vscodeApi.postMessage({ type: 'screenshot', data });
    }
});

// --- Rendering ---

function render(data: ModelData): void {
    clear();

    const nodeMap = buildMap(data.nodes, data.ndm);
    const modelSize = getSize(nodeMap);
    const center = getCenter(nodeMap);

    addNodes(nodeMap);
    addElements(data.elements, nodeMap, data.viewer);
    addSupports(data.supports, nodeMap, data.ndm, modelSize);
    addLoads(data.nodal_loads, nodeMap, data.ndm, modelSize);
    if (data.ndm === 3) addGrid(modelSize, center);
    addLabels(data.nodes, data.elements, data.nodal_loads, nodeMap, data.ndm);

    initCamera(data.ndm, modelSize, center);

    gizmo?.dispose();
    gizmo = null;
    if (data.ndm === 3) {
        gizmo = new ViewportGizmo(camera, renderer, {
            placement: 'top-right',
            size: 100,
            y: { label: 'Z' },
            z: { label: 'Y' },
        });
        gizmo.attachControls(controls);
    }

    lastElements = data.elements;
    lastNodes = data.nodes;
    lastNdm = data.ndm;
    lastNdf = data.ndf;
    lastNodeMap = nodeMap;
    lastViewer = data.viewer;
    lastAnalysis = null;
    selectedElementTag = null;
    forceSelector.style.display = 'none';
    colorbar.style.display = 'none';
    resultsPanel.style.display = 'none';
    diagramPanel.style.display = 'none';
}

function clear(): void {
    for (const obj of modelObjects) {
        scene.remove(obj);
        if ('geometry' in obj && obj.geometry instanceof THREE.BufferGeometry) {
            obj.geometry.dispose();
        }
    }
    modelObjects.length = 0;
    lineMaterial = null;

    for (const group of [nodeLabelGroup, elementLabelGroup, loadLabelGroup]) {
        for (const obj of group.children) {
            if (obj instanceof THREE.Sprite) obj.material.map?.dispose();
        }
        group.clear();
    }
}

function add(obj: THREE.Object3D): void {
    scene.add(obj);
    modelObjects.push(obj);
}

// --- Geometry builders ---

function buildMap(nodes: Node[], ndm: number): Map<number, THREE.Vector3> {
    const map = new Map<number, THREE.Vector3>();
    for (const node of nodes) {
        const x = node.coords[0] ?? 0;
        const y = node.coords[1] ?? 0;
        const z = node.coords[2] ?? 0;
        // 3-D: map struct(X,Y,Z) → Three.js(Y, Z, X)  so structural Z (up) = Three.js Y (up)
        // 2-D: map struct(X,Y)   → Three.js(X, Y, 0)  — natural for OrbitControls
        if (ndm === 3) {
            map.set(node.tag, new THREE.Vector3(y, z, x));
        } else {
            map.set(node.tag, new THREE.Vector3(x, y, 0));
        }
    }
    return map;
}

function getSize(nodeMap: Map<number, THREE.Vector3>): number {
    if (nodeMap.size === 0) return 1;
    const box = new THREE.Box3();
    for (const v of nodeMap.values()) box.expandByPoint(v);
    const size = new THREE.Vector3();
    box.getSize(size);
    return Math.max(size.x, size.y, size.z, 1);
}

function getCenter(nodeMap: Map<number, THREE.Vector3>): THREE.Vector3 {
    if (nodeMap.size === 0) return new THREE.Vector3();
    const box = new THREE.Box3();
    for (const v of nodeMap.values()) box.expandByPoint(v);
    const center = new THREE.Vector3();
    box.getCenter(center);
    return center;
}

function makeLabel(text: string, pos: THREE.Vector3): THREE.Sprite {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 32;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, 128, 32);
    ctx.fillStyle = '#000000';
    ctx.font = 'bold 18px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 64, 16);
    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, sizeAttenuation: false });
    const sprite = new THREE.Sprite(mat);
    sprite.position.copy(pos);
    sprite.scale.set(0.06, 0.016, 1);
    return sprite;
}

function fmtLoad(values: number[], ndm: number): string {
    return values.slice(0, ndm).map(v => {
        const s = v.toPrecision(3);
        return s.includes('.') ? s.replace(/\.?0+$/, '') : s;
    }).join(', ');
}

function addLabels(
    nodes: Node[],
    elements: Element[],
    loads: NodalLoad[],
    nodeMap: Map<number, THREE.Vector3>,
    ndm: number,
): void {
    for (const node of nodes) {
        const pos = nodeMap.get(node.tag);
        if (!pos) continue;
        nodeLabelGroup.add(makeLabel(`N${node.tag}`, pos.clone()));
    }
    for (const el of elements) {
        const a = nodeMap.get(el.nodes[0]);
        const b = nodeMap.get(el.nodes[el.nodes.length - 1]);
        if (!a || !b) continue;
        elementLabelGroup.add(makeLabel(`E${el.tag}`, a.clone().lerp(b, 0.5)));
    }
    if (loads.length > 0) {
        let maxMag = 0;
        for (const load of loads) maxMag = Math.max(maxMag, toVec(load.values, ndm).length());
        if (maxMag >= 1e-12) {
            const arrowScale = 0.5 / maxMag;
            for (const load of loads) {
                const pos = nodeMap.get(load.tag);
                if (!pos) continue;
                const force = toVec(load.values, ndm);
                if (force.length() < 1e-12) continue;
                const dir = force.clone().normalize();
                const tail = pos.clone().sub(dir.clone().multiplyScalar(force.length() * arrowScale));
                loadLabelGroup.add(makeLabel(fmtLoad(load.values, ndm), tail));
            }
        }
    }
    updateLabelVisibility();
}

function addNodes(nodeMap: Map<number, THREE.Vector3>): void {
    const positions: number[] = [];
    nodeTagsByIndex = [];
    for (const [tag, v] of nodeMap.entries()) {
        positions.push(v.x, v.y, v.z);
        nodeTagsByIndex.push(tag);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    add(new THREE.Points(geo, new THREE.PointsMaterial({ color: 0x6699cc, size: 5, sizeAttenuation: false })));
}

function sectionColorMap(viewer: Viewer | undefined): Map<number, THREE.Color> {
    const map = new Map<number, THREE.Color>();
    if (!viewer?.sections) return map;
    for (const sec of viewer.sections) {
        if (sec.tag != null && sec.color) map.set(sec.tag, new THREE.Color(sec.color));
    }
    return map;
}

function addElements(
    elements: Element[],
    nodeMap: Map<number, THREE.Vector3>,
    viewer: Viewer | undefined,
): void {
    const positions: number[] = [];
    elementTagsBySegment = [];
    segmentsPerElement = NEP - 1;

    for (const el of elements) {
        const a = nodeMap.get(el.nodes[0]);
        const b = nodeMap.get(el.nodes[el.nodes.length - 1]);
        if (!a || !b) continue;
        // Subdivide into NEP-1 segments using uniform spacing
        for (let k = 0; k < segmentsPerElement; k++) {
            const t0 = k / segmentsPerElement;
            const t1 = (k + 1) / segmentsPerElement;
            const p0 = a.clone().lerp(b, t0);
            const p1 = a.clone().lerp(b, t1);
            positions.push(p0.x, p0.y, p0.z, p1.x, p1.y, p1.z);
            elementTagsBySegment.push(el.tag);
        }
    }
    if (positions.length === 0) return;

    const geo = new LineSegmentsGeometry();
    geo.setPositions(positions);

    // Assign per-vertex colors: section color if available, else default steel-blue
    const defaultColor = new THREE.Color(0x88aadd);
    const secColors = sectionColorMap(viewer);
    const colors: number[] = [];
    for (const el of elements) {
        const a = nodeMap.get(el.nodes[0]);
        const b = nodeMap.get(el.nodes[el.nodes.length - 1]);
        if (!a || !b) continue;
        const col = (el.section != null ? secColors.get(el.section) : undefined) ?? defaultColor;
        for (let k = 0; k < segmentsPerElement; k++) {
            colors.push(col.r, col.g, col.b, col.r, col.g, col.b);
        }
    }
    geo.setColors(colors);

    lineMaterial = new LineMaterial({
        vertexColors: true,
        linewidth: 4,
        resolution: new THREE.Vector2(window.innerWidth, window.innerHeight),
    });

    add(new LineSegments2(geo, lineMaterial));
}

function addSupports(
    supports: Support[],
    nodeMap: Map<number, THREE.Vector3>,
    ndm: number,
    modelSize: number,
): void {
    const h = modelSize * 0.048;
    const r = modelSize * 0.016;
    const mat = new THREE.MeshBasicMaterial({ color: 0x66ddcc, side: THREE.DoubleSide });

    for (const support of supports) {
        const pos = nodeMap.get(support.tag);
        if (!pos) continue;

        const fullyFixed = support.dofs.length > 0 && support.dofs.every(d => d === 1);

        if (fullyFixed) {
            // Solid box centered at node
            const geo = new THREE.BoxGeometry(r * 2, r * 2, r * 2);
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.copy(pos);
            add(mesh);
        } else if (ndm === 3) {
            // Solid inverted cone: apex at node, base below
            // ConeGeometry points up by default (apex at +Y), rotate 180° so apex is at top (node)
            const geo = new THREE.ConeGeometry(r, h, 16);
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(pos.x, pos.y - h / 2, pos.z);
            add(mesh);
        } else {
            // 2D: solid filled triangle
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                pos.x,      pos.y,      0,
                pos.x - r,  pos.y - h,  0,
                pos.x + r,  pos.y - h,  0,
            ]), 3));
            geo.setIndex([0, 1, 2]);
            geo.computeVertexNormals();
            add(new THREE.Mesh(geo, mat));
        }
    }
}

function addLoads(
    loads: NodalLoad[],
    nodeMap: Map<number, THREE.Vector3>,
    ndm: number,
    modelSize: number,
): void {
    if (loads.length === 0) return;
    const length = modelSize * 0.15;
    for (const load of loads) {
        const pos = nodeMap.get(load.tag);
        if (!pos) continue;
        const force = toVec(load.values, ndm);
        if (force.length() < 1e-12) continue;
        const dir = force.clone().normalize();
        const origin = pos.clone().sub(dir.clone().multiplyScalar(length));
        add(new THREE.ArrowHelper(dir, origin, length, 0xff4444, length * 0.2, length * 0.1));
    }
}

function addGrid(modelSize: number, center: THREE.Vector3): void {
    const size = modelSize * 2.5;
    const divisions = 20;
    const grid = new THREE.GridHelper(size, divisions, 0x333355, 0x282844);
    // Ground plane is at Three.js Y = 0 (structural Z = 0)
    grid.position.set(center.x, 0, center.z);
    add(grid);
}

function addAxes(ndm: number, center: THREE.Vector3, modelSize: number): void {
    const len = modelSize * 0.2;
    if (ndm === 2) {
        [{ dx: len, dy: 0, color: 0xff4444 }, { dx: 0, dy: len, color: 0x44ff44 }].forEach(({ dx, dy, color }) => {
            const pts = new Float32Array([center.x, center.y, 0, center.x + dx, center.y + dy, 0]);
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(pts, 3));
            add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color })));
        });
    } else {
        const axes = new THREE.AxesHelper(len);
        axes.position.copy(center);
        add(axes);
    }
}

function toVec(values: number[], ndm: number): THREE.Vector3 {
    if (ndm === 3) {
        // Match buildMap remapping: structural (X,Y,Z) → Three.js (Y,Z,X)
        return new THREE.Vector3(values[1] ?? 0, values[2] ?? 0, values[0] ?? 0);
    }
    return new THREE.Vector3(values[0] ?? 0, values[1] ?? 0, 0);
}

// --- Element colormap ---

function populateForceSelector(ndf: number): void {
    const components = forceComponents(ndf);
    forceSelect.innerHTML =
        '<option value="">— Select result —</option>' +
        components.map((c, i) => `<option value="${i}">${c.label}</option>`).join('');
}

function restoreDefaultColors(
    elements: Element[],
    nodeMap: Map<number, THREE.Vector3>,
): void {
    const defaultColor = new THREE.Color(0x88aadd);
    const secColors = sectionColorMap(lastViewer);
    const colors: number[] = [];
    for (const el of elements) {
        const a = nodeMap.get(el.nodes[0]);
        const b = nodeMap.get(el.nodes[el.nodes.length - 1]);
        if (!a || !b) continue;
        const col = (el.section != null ? secColors.get(el.section) : undefined) ?? defaultColor;
        for (let k = 0; k < segmentsPerElement; k++) {
            colors.push(col.r, col.g, col.b, col.r, col.g, col.b);
        }
    }
    for (const obj of modelObjects) {
        if (obj instanceof LineSegments2) {
            (obj.geometry as LineSegmentsGeometry).setColors(colors);
            break;
        }
    }
    colorbar.style.display = 'none';
}

function recolorElements(
    elements: Element[],
    nodeMap: Map<number, THREE.Vector3>,
    analysis: AnalysisData,
): void {
    const components = forceComponents(lastNdf);
    const selectedIdx = parseInt(forceSelect.value, 10);
    const component = components[selectedIdx];
    if (!component) return;

    const key = component.key;

    // Build tag → section forces lookup
    const resultMap = new Map<number, ElementResult>();
    for (const er of analysis.element_results) resultMap.set(er.tag, er);

    // Find global min/max across all evaluation points
    const allValues: number[] = [];
    for (const er of analysis.element_results) {
        const vals = er.section_forces[key];
        if (vals) for (const v of vals) allValues.push(v);
    }
    if (allValues.length === 0) return;
    const min = Math.min(...allValues);
    const max = Math.max(...allValues);
    const range = max - min || 1;

    // Build per-vertex colors — each segment gets start/end colors from evaluation points
    const colors: number[] = [];
    for (const el of elements) {
        const a = nodeMap.get(el.nodes[0]);
        const b = nodeMap.get(el.nodes[el.nodes.length - 1]);
        if (!a || !b) continue;
        const er = resultMap.get(el.tag);
        const vals = er?.section_forces[key];
        for (let k = 0; k < segmentsPerElement; k++) {
            const vStart = vals ? vals[k] : 0;
            const vEnd = vals ? vals[k + 1] : 0;
            const tStart = (vStart - min) / range;
            const tEnd = (vEnd - min) / range;
            const colStart = rainbow(tStart);
            const colEnd = rainbow(tEnd);
            colors.push(colStart.r, colStart.g, colStart.b, colEnd.r, colEnd.g, colEnd.b);
        }
    }

    // Find the LineSegments2 and update its colors
    for (const obj of modelObjects) {
        if (obj instanceof LineSegments2) {
            (obj.geometry as LineSegmentsGeometry).setColors(colors);
            break;
        }
    }

    updateColorbar(component.label, min, max);
}

function updateColorbar(title: string, min: number, max: number): void {
    colorbar.style.display = 'block';
    colorbarTitle.textContent = title;
    colorbarMin.textContent = exp(min);
    colorbarMax.textContent = exp(max);

    const ctx = colorbarCanvas.getContext('2d') as CanvasRenderingContext2D;
    const w = colorbarCanvas.width;
    const h = colorbarCanvas.height;
    for (let i = 0; i < h; i++) {
        // Top = max (red, t=1), bottom = min (blue, t=0)
        const col = rainbow(1 - i / (h - 1));
        ctx.fillStyle = `rgb(${Math.round(col.r * 255)},${Math.round(col.g * 255)},${Math.round(col.b * 255)})`;
        ctx.fillRect(0, i, w, 1);
    }
}

// --- Results table ---

function precision(): number {
    return lastViewer?.precision ?? 3;
}

function exp(v: number): string {
    return v.toExponential(precision());
}

function fmt(v: number | undefined): string {
    return v !== undefined ? v.toFixed(precision()) : '—';
}

function buildTable(): void {
    if (currentTab === 'nodes') buildNodeTable();
    else buildElementTable();
}

function dofLabels(ndf: number, prefix: string): string[] {
    if (ndf <= 2) return [`${prefix}X`, `${prefix}Y`];
    if (ndf === 3) return [`${prefix}X`, `${prefix}Y`, `${prefix}Rz`];
    return [`${prefix}X`, `${prefix}Y`, `${prefix}Z`, `${prefix}Rx`, `${prefix}Ry`, `${prefix}Rz`];
}

function buildNodeTable(): void {
    if (!lastAnalysis) return;
    const coordHeaders = lastNdm === 3 ? ['X', 'Y', 'Z'] : ['X', 'Y'];
    const dispHeaders = dofLabels(lastNdf, 'd');
    const reactHeaders = dofLabels(lastNdf, 'R');

    resultsThead.innerHTML = '<tr>' +
        ['Tag', ...coordHeaders, ...dispHeaders, ...reactHeaders]
            .map(h => `<th>${h}</th>`).join('') +
        '</tr>';

    const rows: string[] = [];
    for (const node of lastNodes) {
        const nr = lastAnalysis.node_results.find(r => r.tag === node.tag);
        const coords = coordHeaders.map((_, i) => `<td>${fmt(node.coords[i])}</td>`).join('');
        const disps = dispHeaders.map((_, i) => `<td>${nr && nr.disp[i] != null ? exp(nr.disp[i]) : '—'}</td>`).join('');
        const reacts = reactHeaders.map((_, i) => `<td>${nr && nr.reaction[i] != null ? exp(nr.reaction[i]) : '—'}</td>`).join('');
        rows.push(`<tr data-type="node" data-tag="${node.tag}"><td>${node.tag}</td>${coords}${disps}${reacts}</tr>`);
    }
    resultsTbody.innerHTML = rows.join('');
}

function buildElementTable(): void {
    if (!lastAnalysis) return;
    const comps = forceComponents(lastNdf);
    const startHeaders = comps.map(c => `${c.label} (i)`);
    const endHeaders = comps.map(c => `${c.label} (j)`);

    resultsThead.innerHTML = '<tr>' +
        ['Tag', 'Type', 'Nodes', ...startHeaders, ...endHeaders]
            .map(h => `<th>${h}</th>`).join('') +
        '</tr>';

    const rows: string[] = [];
    for (const el of lastElements) {
        const er = lastAnalysis.element_results.find(r => r.tag === el.tag);
        const sf = er?.section_forces;
        const startForces = comps.map(c => {
            const vals = sf?.[c.key];
            return `<td>${vals ? exp(vals[0]) : '—'}</td>`;
        }).join('');
        const endForces = comps.map(c => {
            const vals = sf?.[c.key];
            return `<td>${vals ? exp(vals[vals.length - 1]) : '—'}</td>`;
        }).join('');
        rows.push(`<tr data-type="element" data-tag="${el.tag}"><td>${el.tag}</td><td>${el.type}</td><td>${el.nodes.join('→')}</td>${startForces}${endForces}</tr>`);
    }
    resultsTbody.innerHTML = rows.join('');
}

// --- Element selection & diagram ---

const diagramPanel  = document.getElementById('diagram-panel') as HTMLDivElement;
const diagramTitle  = document.getElementById('diagram-title') as HTMLSpanElement;
const diagramClose  = document.getElementById('diagram-close') as HTMLButtonElement;
const diagramCanvas = document.getElementById('diagram-canvas') as HTMLCanvasElement;

diagramClose.addEventListener('click', () => deselectElement());

resultsTbody.addEventListener('click', (e: MouseEvent) => {
    const row = (e.target as HTMLElement).closest('tr');
    if (!row || row.dataset.type !== 'element') return;
    const tag = parseInt(row.dataset.tag!, 10);
    selectElement(tag);
});

function selectElement(tag: number): void {
    deselectElement();
    selectedElementTag = tag;

    // Highlight table row
    const rows = Array.from(resultsTbody.querySelectorAll('tr[data-type="element"]'));
    for (const row of rows) {
        if (parseInt((row as HTMLElement).dataset.tag!, 10) === tag) {
            row.classList.add('selected');
        }
    }

    // Highlight element segments in 3D (white)
    highlightElement(tag);

    // Show diagram
    if (!lastAnalysis) return;
    const er = lastAnalysis.element_results.find(r => r.tag === tag);
    if (!er) return;
    diagramTitle.textContent = `Element ${tag}`;
    diagramPanel.style.display = 'block';
    drawDiagram(er);
}

function deselectElement(): void {
    if (selectedElementTag === null) return;
    selectedElementTag = null;
    diagramPanel.style.display = 'none';

    // Remove table highlight
    const rows = Array.from(resultsTbody.querySelectorAll('tr.selected'));
    for (const row of rows) row.classList.remove('selected');

    // Restore element colors
    if (forceSelect.value !== '' && lastAnalysis) {
        recolorElements(lastElements, lastNodeMap, lastAnalysis);
    } else {
        restoreDefaultColors(lastElements, lastNodeMap);
    }
}

function highlightElement(tag: number): void {
    // Override colors for selected element's segments to white
    for (const obj of modelObjects) {
        if (!(obj instanceof LineSegments2)) continue;
        const geo = obj.geometry as LineSegmentsGeometry;
        const colorAttr = geo.getAttribute('instanceColorStart');
        const colorEndAttr = geo.getAttribute('instanceColorEnd');
        if (!colorAttr || !colorEndAttr) continue;

        for (let i = 0; i < elementTagsBySegment.length; i++) {
            if (elementTagsBySegment[i] === tag) {
                colorAttr.setXYZ(i, 1, 1, 1);
                colorEndAttr.setXYZ(i, 1, 1, 1);
            }
        }
        colorAttr.needsUpdate = true;
        colorEndAttr.needsUpdate = true;
        break;
    }
}

// --- Diagram rendering ---

function drawDiagram(er: ElementResult): void {
    const sf = er.section_forces;
    const ctx = diagramCanvas.getContext('2d')!;

    const plots: { label: string; values: number[] }[] = [];
    if (sf.N) plots.push({ label: 'N (Axial)', values: sf.N });
    if (sf.V) plots.push({ label: 'V (Shear)', values: sf.V });
    if (sf.M) plots.push({ label: 'M (Moment)', values: sf.M });
    if (sf.T) plots.push({ label: 'T (Torsion)', values: sf.T });
    if (sf.Vz) plots.push({ label: 'Vz (Shear Z)', values: sf.Vz });
    if (sf.My) plots.push({ label: 'My', values: sf.My });
    if (sf.Mz) plots.push({ label: 'Mz', values: sf.Mz });

    if (plots.length === 0) return;

    const subH = 100;
    const pad = { top: 20, bottom: 10, left: 50, right: 20 };
    diagramCanvas.width = diagramPanel.clientWidth - 16;
    diagramCanvas.height = plots.length * (subH + pad.top + pad.bottom);

    for (let i = 0; i < plots.length; i++) {
        const yOffset = i * (subH + pad.top + pad.bottom);
        drawSubplot(ctx, sf.x, plots[i].values, plots[i].label,
                    pad.left, yOffset + pad.top,
                    diagramCanvas.width - pad.left - pad.right, subH);
    }
}

function drawSubplot(
    ctx: CanvasRenderingContext2D,
    x: number[], values: number[],
    label: string,
    ox: number, oy: number,
    w: number, h: number,
): void {
    const vMin = Math.min(0, ...values);
    const vMax = Math.max(0, ...values);
    const vRange = vMax - vMin || 1;

    const yPx = (v: number): number => oy + h - ((v - vMin) / vRange) * h;
    const xPx = (t: number): number => ox + t * w;
    const zeroY = yPx(0);

    // Label
    ctx.fillStyle = '#e0e0e0';
    ctx.font = '11px sans-serif';
    ctx.fillText(label, ox, oy - 4);

    // Zero line (dashed)
    ctx.strokeStyle = '#666688';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(ox, zeroY);
    ctx.lineTo(ox + w, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Filled polygon: baseline → curve → baseline
    ctx.beginPath();
    ctx.moveTo(xPx(x[0]), zeroY);
    for (let k = 0; k < x.length; k++) {
        ctx.lineTo(xPx(x[k]), yPx(values[k]));
    }
    ctx.lineTo(xPx(x[x.length - 1]), zeroY);
    ctx.closePath();
    ctx.fillStyle = 'rgba(78, 154, 200, 0.4)';
    ctx.fill();

    // Outline
    ctx.strokeStyle = '#4e9ac8';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let k = 0; k < x.length; k++) {
        if (k === 0) ctx.moveTo(xPx(x[k]), yPx(values[k]));
        else ctx.lineTo(xPx(x[k]), yPx(values[k]));
    }
    ctx.stroke();
    ctx.lineWidth = 1;

    // Min/max value labels
    const p = precision();
    const maxIdx = values.indexOf(Math.max(...values));
    const minIdx = values.indexOf(Math.min(...values));
    ctx.fillStyle = '#aaaacc';
    ctx.font = '10px monospace';
    ctx.fillText(values[maxIdx].toExponential(p), xPx(x[maxIdx]) + 4, yPx(values[maxIdx]) - 4);
    if (minIdx !== maxIdx) {
        ctx.fillText(values[minIdx].toExponential(p), xPx(x[minIdx]) + 4, yPx(values[minIdx]) + 12);
    }
}

// --- Camera & controls ---

function initCamera(ndm: number, modelSize: number, center: THREE.Vector3): void {
    controls.dispose();
    camera = ndm === 2 ? setOrthographic(modelSize, center) : setPerspective(modelSize, center);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.copy(center);
    if (ndm === 2) controls.enableRotate = false;
    controls.update();
    gizmo?.attachControls(controls);
}

function defaultCamera(): THREE.PerspectiveCamera {
    const cam = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.001, 100000);
    cam.position.set(0, 0, 10);
    return cam;
}

function setPerspective(modelSize: number, center: THREE.Vector3): THREE.PerspectiveCamera {
    const cam = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, modelSize * 0.001, modelSize * 100);
    const dist = (modelSize / (2 * Math.tan((45 * Math.PI) / 360))) * 1.6;
    // Position camera to the side and slightly above — works naturally with Y-up after coord remap
    cam.position.set(center.x + dist * 0.8, center.y + dist * 0.4, center.z + dist * 0.8);
    cam.lookAt(center);
    return cam;
}

function setOrthographic(modelSize: number, center: THREE.Vector3): THREE.OrthographicCamera {
    const aspect = window.innerWidth / window.innerHeight;
    const half = modelSize * 0.8;
    const cam = new THREE.OrthographicCamera(-half * aspect, half * aspect, half, -half, 0.1, modelSize * 100 + 1000);
    cam.position.set(center.x, center.y, modelSize * 10);
    cam.lookAt(center);
    return cam;
}

// --- UI helpers ---

function setStatus(text: string): void { statusEl.textContent = text; }
function showError(message: string): void { errorBanner.style.display = 'block'; errorBanner.textContent = message; }
function hideError(): void { errorBanner.style.display = 'none'; }

// --- Signal ready ---
vscodeApi.postMessage({ type: 'ready' });
