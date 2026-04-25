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

export interface Responses {
    localForce?: number[];
}

export interface ElementOutput {
    eleTag: number;
    type: string;
    nodes: number[];
    responses: Responses;
}

export interface NodeOutput {
    tag: number;
    coords: number[];
    displacement: number[];
    reaction: number[];
}

export interface ElasticSection {
    type: 'Elastic';
    eleTag: number;
    E: number;
    A: number;
    Iz?: number;
    Iy?: number;
    G?: number;
    J?: number;
}

export type SectionOutput = ElasticSection;

export interface Outputs {
    nodes: NodeOutput[];
    elements: ElementOutput[];
    sections: SectionOutput[];
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
    tools: string[];
}

export interface AnalysisRunnerOutput extends ModelData {
    outputs?: Outputs;
}

export interface ToolElementOutput {
    tag: number;
    name: string;
    value: number | string | boolean;
    description?: string;
}

export interface ToolOutput {
    name: string;
    elements: ToolElementOutput[];
}

export type WebViewMessage =
    | { type: 'modelData'; data: ModelData }
    | { type: 'analysisData'; data: Outputs; ndf: number }
    | { type: 'toolUse'; data: ToolOutput[] }
    | { type: 'loading' }
    | { type: 'analysisRunning' }
    | { type: 'error'; message: string }
    | { type: 'takeScreenshot' };

export type ViewerMessage =
    | { type: 'ready' }
    | { type: 'runAnalysis' }
    | { type: 'screenshot'; data: string };
