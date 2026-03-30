export interface Node {
    tag: number;
    coords: number[];
}

export interface Element {
    tag: number;
    type: string;
    nodes: number[];
    section?: number;
}

export interface Support {
    tag: number;
    dofs: number[];
}

export interface NodalLoad {
    tag: number;
    values: number[];
}

export interface NodeResult {
    tag: number;
    disp: number[];
    reaction: number[];
}

export interface SectionForces {
    x: number[];
    N: number[];
    V?: number[];
    M?: number[];
    Vz?: number[];
    T?: number[];
    My?: number[];
    Mz?: number[];
}

export interface ElementResult {
    tag: number;
    local_forces: number[];
    section_forces: SectionForces;
}

export interface CustomElemResult {
    id: string;
    name: string;
    values: Record<number, number[]>;
}

export interface AnalysisData {
    converged: boolean;
    node_results: NodeResult[];
    element_results: ElementResult[];
    ops_elem_results?: CustomElemResult[];
}

export interface Section {
    tag?: number;
    color?: string;
    label?: string;
}

export interface NodalLoads {
    scale?: number;
    color?: string;
}

export interface Supports {
    scale?: number;
    color?: string;
}

export interface Label {
    size?: number;
}

export interface Viewer {
    sections?: Section[];
    precision?: number;
    nodalLoads?: NodalLoads;
    supports?: Supports;
    label?: Label;
}

export interface ModelData {
    schema_version: number;
    ndm: number;
    ndf: number;
    nodes: Node[];
    elements: Element[];
    supports: Support[];
    nodal_loads: NodalLoad[];
    viewer?: Viewer;
    error: string | null;
}

export interface AnalysisRunnerOutput extends ModelData {
    analysis?: AnalysisData;
}

export type WebViewMessage =
    | { type: 'modelData'; data: ModelData }
    | { type: 'analysisData'; data: AnalysisData; ndf: number }
    | { type: 'loading' }
    | { type: 'analysisRunning' }
    | { type: 'error'; message: string }
    | { type: 'takeScreenshot' };

export type ViewerMessage =
    | { type: 'ready' }
    | { type: 'runAnalysis' }
    | { type: 'screenshot'; data: string };
