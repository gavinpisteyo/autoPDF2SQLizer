import { useCallback, useState } from 'react';

export type WorkflowState =
  | 'SELECT_PROJECT'
  | 'DEFINE_SCHEMA'
  | 'UPLOAD'
  | 'EXTRACTING'
  | 'REVIEW_RESULTS'
  | 'OPTIMIZING'
  | 'COMPLETE'
  | 'READY';

export interface ProjectInfo {
  id: string;
  name: string;
  slug: string;
  description?: string;
  member_count?: number;
  has_schema?: boolean;
  is_optimized?: boolean;
}

export interface WorkflowData {
  workflowState: WorkflowState;
  selectedProject: ProjectInfo | null;
  schema: Record<string, unknown> | null;
  docTypeKey: string;
  uploadedFile: File | null;
  groundTruthFile: File | null;
  hasExample: boolean;
  extractionResults: Record<string, unknown> | null;
  optimizationRunId: string | null;
  sourceFile: string;
}

export interface WorkflowActions {
  selectProject: (project: ProjectInfo) => void;
  startCreateProject: (name: string) => void;
  setSchemaGenerated: (docTypeKey: string, schema: Record<string, unknown>, projectId: string) => void;
  setUploadedFile: (file: File | null) => void;
  setGroundTruthFile: (file: File | null) => void;
  setHasExample: (has: boolean) => void;
  startExtraction: () => void;
  setExtractionResults: (results: Record<string, unknown>, sourceFile: string, docType?: string) => void;
  startOptimization: (runId: string) => void;
  completeOptimization: () => void;
  uploadAnother: () => void;
  reset: () => void;
  goToUpload: () => void;
}

const INITIAL_DATA: WorkflowData = {
  workflowState: 'SELECT_PROJECT',
  selectedProject: null,
  schema: null,
  docTypeKey: '',
  uploadedFile: null,
  groundTruthFile: null,
  hasExample: false,
  extractionResults: null,
  optimizationRunId: null,
  sourceFile: '',
};

export function useDocumentWorkflow() {
  const [data, setData] = useState<WorkflowData>({ ...INITIAL_DATA });

  const selectProject = useCallback((project: ProjectInfo) => {
    const nextState: WorkflowState = project.is_optimized ? 'READY' : 'UPLOAD';
    setData(prev => ({
      ...prev,
      workflowState: nextState,
      selectedProject: project,
      docTypeKey: project.slug,
    }));
  }, []);

  const startCreateProject = useCallback((name: string) => {
    setData(prev => ({
      ...prev,
      workflowState: 'DEFINE_SCHEMA',
      selectedProject: { id: '', name, slug: name.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '') },
    }));
  }, []);

  const setSchemaGenerated = useCallback((docTypeKey: string, schema: Record<string, unknown>, projectId: string) => {
    setData(prev => ({
      ...prev,
      workflowState: 'UPLOAD',
      schema,
      docTypeKey,
      selectedProject: prev.selectedProject
        ? { ...prev.selectedProject, id: projectId, has_schema: true }
        : null,
    }));
  }, []);

  const setUploadedFile = useCallback((file: File | null) => {
    setData(prev => ({ ...prev, uploadedFile: file }));
  }, []);

  const setGroundTruthFile = useCallback((file: File | null) => {
    setData(prev => ({ ...prev, groundTruthFile: file }));
  }, []);

  const setHasExample = useCallback((has: boolean) => {
    setData(prev => ({
      ...prev,
      hasExample: has,
      groundTruthFile: has ? prev.groundTruthFile : null,
    }));
  }, []);

  const startExtraction = useCallback(() => {
    setData(prev => ({ ...prev, workflowState: 'EXTRACTING' }));
  }, []);

  const setExtractionResults = useCallback((results: Record<string, unknown>, sourceFile: string, docType?: string) => {
    setData(prev => ({
      ...prev,
      workflowState: 'REVIEW_RESULTS',
      extractionResults: results,
      sourceFile,
      docTypeKey: docType || prev.docTypeKey,
    }));
  }, []);

  const startOptimization = useCallback((runId: string) => {
    setData(prev => ({
      ...prev,
      workflowState: 'OPTIMIZING',
      optimizationRunId: runId,
    }));
  }, []);

  const completeOptimization = useCallback(() => {
    setData(prev => ({
      ...prev,
      workflowState: 'COMPLETE',
    }));
  }, []);

  const uploadAnother = useCallback(() => {
    setData(prev => ({
      ...prev,
      workflowState: 'READY',
      uploadedFile: null,
      groundTruthFile: null,
      hasExample: false,
      extractionResults: null,
      sourceFile: '',
    }));
  }, []);

  const reset = useCallback(() => {
    setData({ ...INITIAL_DATA });
  }, []);

  const goToUpload = useCallback(() => {
    setData(prev => ({
      ...prev,
      workflowState: 'UPLOAD',
      uploadedFile: null,
      groundTruthFile: null,
      hasExample: false,
      extractionResults: null,
      sourceFile: '',
    }));
  }, []);

  const actions: WorkflowActions = {
    selectProject,
    startCreateProject,
    setSchemaGenerated,
    setUploadedFile,
    setGroundTruthFile,
    setHasExample,
    startExtraction,
    setExtractionResults,
    startOptimization,
    completeOptimization,
    uploadAnother,
    reset,
    goToUpload,
  };

  return { ...data, ...actions };
}
