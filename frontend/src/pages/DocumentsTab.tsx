import { useCallback, useEffect, useState } from 'react';
import { useAuthContext } from '../lib/auth';
import { useDocumentWorkflow } from '../hooks/useDocumentWorkflow';
import type { ProjectInfo } from '../hooks/useDocumentWorkflow';
import ProjectSelector from '../components/ProjectSelector';
import SchemaGenerator from '../components/SchemaGenerator';
import UploadArea from '../components/UploadArea';
import ResultsTable from '../components/ResultsTable';
import OptimizationBanner from '../components/OptimizationBanner';
import StatusMessage from '../components/StatusMessage';
import type { ApiClient } from '../lib/api';

interface DocumentsTabProps {
  api: ApiClient;
  onGoToChat: () => void;
}

type SchemaProps = Record<string, { type?: string; [k: string]: unknown }>;

export default function DocumentsTab({ api, onGoToChat }: DocumentsTabProps) {
  const { setProjectId, projectId: authProjectId } = useAuthContext();
  const workflow = useDocumentWorkflow();
  const [status, setStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });
  const [saving, setSaving] = useState(false);
  const [schema, setSchema] = useState<SchemaProps>({});
  const [documents, setDocuments] = useState<Array<{ name: string; doc_type: string; date?: string }>>([]);
  const [restoredProject, setRestoredProject] = useState(false);

  // On mount: restore active project from auth context (survives page reload)
  useEffect(() => {
    if (restoredProject || workflow.workflowState !== 'SELECT_PROJECT') return;
    if (!authProjectId) { setRestoredProject(true); return; }

    // Fetch the project and auto-select it
    api.getProject(authProjectId).then((project: ProjectInfo) => {
      if (project?.id) {
        // Check if there's an active optimization run
        api.getWiggumStatus(project.id).then((ws: { status: string }) => {
          if (ws.status === 'in_progress' || ws.status === 'pending' || ws.status === 'queued') {
            workflow.selectProject(project);
            workflow.startOptimization('');
          } else {
            workflow.selectProject(project);
          }
        }).catch(() => {
          workflow.selectProject(project);
        });
      }
    }).catch(() => {}).finally(() => setRestoredProject(true));
  }, [authProjectId, restoredProject, api, workflow]);

  // Load schema whenever project changes
  const loadSchema = useCallback(async (projectId: string) => {
    try {
      const data = await api.getProjectSchema(projectId);
      const props = data?.properties || data?.schema?.properties;
      if (props) setSchema(props as SchemaProps);
    } catch {}
  }, [api]);

  // Load documents list for the project
  const loadDocuments = useCallback(async () => {
    if (!workflow.selectedProject?.id) return;
    try {
      const gt = await api.listGroundTruth();
      setDocuments(Array.isArray(gt) ? gt.map((d: { name: string; doc_type: string }) => ({
        name: d.name, doc_type: d.doc_type, date: 'Uploaded',
      })) : []);
    } catch {
      setDocuments([]);
    }
  }, [api, workflow.selectedProject?.id]);

  useEffect(() => {
    if (workflow.selectedProject?.id && workflow.workflowState !== 'SELECT_PROJECT' && workflow.workflowState !== 'DEFINE_SCHEMA') {
      loadSchema(workflow.selectedProject.id);
      loadDocuments();
    }
  }, [workflow.selectedProject?.id, workflow.workflowState, loadSchema, loadDocuments]);

  const handleProjectSelected = (project: ProjectInfo) => {
    workflow.selectProject(project);
    if (project.id) setProjectId(project.id);
  };

  const handleSchemaGenerated = (docTypeKey: string, schemaObj: Record<string, unknown>, projectId: string) => {
    workflow.setSchemaGenerated(docTypeKey, schemaObj, projectId);
    if (projectId) setProjectId(projectId);
    const props = (schemaObj as { properties?: SchemaProps }).properties;
    if (props) setSchema(props);
  };

  const handleUploadSubmit = async (pdfFile: File, groundTruthFile?: File) => {
    if (!workflow.selectedProject?.id) return;

    workflow.startExtraction();
    setStatus({ msg: 'Extracting document... this may take a moment.', type: 'loading' });

    try {
      const data = await api.uploadDocument(workflow.selectedProject.id, pdfFile, groundTruthFile);
      const docType = (data.doc_type as string) || workflow.docTypeKey;

      // Load schema from response if available
      const respSchema = data.schema?.properties || data.schema;
      if (respSchema && typeof respSchema === 'object' && Object.keys(respSchema).length > 0) {
        setSchema(respSchema as SchemaProps);
      }

      if (data.extracted) {
        const extracted = data.extracted as Record<string, unknown>;
        const filled = Object.values(extracted).filter(v => v !== null && v !== '' && v !== undefined).length;

        workflow.setExtractionResults(extracted, data.source_file as string || '', docType);

        if (filled === 0) {
          setStatus({ msg: 'No values found in the document. Your schema fields are shown below — fill them in.', type: 'error' });
        } else {
          setStatus({ msg: `Found ${filled} field(s). Review and correct below.`, type: 'success' });
        }
      } else {
        setStatus({ msg: 'Extraction completed.', type: 'success' });
        workflow.completeOptimization();
      }
    } catch (e: unknown) {
      setStatus({ msg: `Extraction error: ${e instanceof Error ? e.message : 'Unknown'}`, type: 'error' });
      workflow.goToUpload();
    }
  };

  const handleSaveCorrections = async (correctedData: Record<string, unknown>) => {
    if (!workflow.selectedProject?.id) return;
    setSaving(true);
    try {
      await api.saveCorrections(
        workflow.selectedProject.id,
        workflow.sourceFile,
        workflow.docTypeKey,
        correctedData,
      );
      // Go to optimization state (banner)
      workflow.startOptimization('');
      setStatus({ msg: 'Corrections saved. Optimization starting...', type: 'success' });
    } catch (e: unknown) {
      setStatus({ msg: `Save error: ${e instanceof Error ? e.message : 'Unknown'}`, type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      {/* Back button */}
      {workflow.workflowState !== 'SELECT_PROJECT' && (
        <button onClick={() => { workflow.reset(); setProjectId(''); }} className="mb-5 text-[0.8125rem] text-mid hover:text-silver transition-colors">
          &larr; Back to projects
        </button>
      )}

      {/* Project header */}
      {workflow.selectedProject && workflow.workflowState !== 'SELECT_PROJECT' && (
        <div className="mb-5 pb-4 border-b border-border">
          <h2 className="font-heading text-lg font-semibold text-cloud tracking-tight">
            {workflow.selectedProject.name}
          </h2>
        </div>
      )}

      {/* SELECT_PROJECT */}
      {workflow.workflowState === 'SELECT_PROJECT' && (
        <ProjectSelector api={api} onProjectSelected={handleProjectSelected} onCreateNew={workflow.startCreateProject} />
      )}

      {/* DEFINE_SCHEMA */}
      {workflow.workflowState === 'DEFINE_SCHEMA' && workflow.selectedProject && (
        <SchemaGenerator api={api} projectName={workflow.selectedProject.name} onSchemaGenerated={handleSchemaGenerated} />
      )}

      {/* UPLOAD / READY */}
      {(workflow.workflowState === 'UPLOAD' || workflow.workflowState === 'READY') && workflow.selectedProject && (
        <div>
          {status.type === 'error' && <StatusMessage message={status.msg} type={status.type} />}

          {/* Previously uploaded documents */}
          {documents.length > 0 && (
            <div className="mb-8">
              <h3 className="text-xs font-semibold text-silver uppercase tracking-wide mb-3">Uploaded Documents</h3>
              <div className="space-y-1.5">
                {documents.map((d, i) => (
                  <div key={i} className="flex items-center justify-between py-2 px-3 bg-surface border border-border-strong rounded-md text-[0.8125rem]">
                    <span className="text-silver">{d.doc_type}/{d.name}</span>
                    <span className="text-[0.6875rem] text-mid">{d.date}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <UploadArea onSubmit={handleUploadSubmit} projectName={workflow.selectedProject.name} />
        </div>
      )}

      {/* EXTRACTING */}
      {workflow.workflowState === 'EXTRACTING' && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="w-3 h-3 rounded-full bg-coral animate-pulse mb-4" />
          <p className="text-[0.8125rem] text-silver mb-2">Extracting document...</p>
          <p className="text-[0.6875rem] text-mid">This may take a moment.</p>
        </div>
      )}

      {/* REVIEW_RESULTS */}
      {workflow.workflowState === 'REVIEW_RESULTS' && (
        <div>
          <StatusMessage message={status.msg} type={status.type} />
          <div className="mt-4">
            <ResultsTable
              data={workflow.extractionResults || {}}
              schema={schema}
              onSave={handleSaveCorrections}
              saving={saving}
            />
          </div>
        </div>
      )}

      {/* OPTIMIZING */}
      {workflow.workflowState === 'OPTIMIZING' && (
        <OptimizationBanner api={api} projectId={workflow.selectedProject?.id || ''} onComplete={workflow.completeOptimization} onGoToChat={onGoToChat} />
      )}

      {/* COMPLETE */}
      {workflow.workflowState === 'COMPLETE' && (
        <div className="text-center py-12">
          <div className="w-12 h-12 rounded-full bg-sage-bg flex items-center justify-center mx-auto mb-4">
            <div className="w-3 h-3 rounded-full bg-sage" />
          </div>
          <h2 className="font-heading text-lg font-semibold text-cloud tracking-tight mb-2">Document Processed</h2>
          <p className="text-[0.8125rem] text-mid font-light mb-6">
            Your data has been extracted and saved. Query it in Chat or upload more documents.
          </p>
          <div className="flex gap-3 justify-center">
            <button onClick={workflow.uploadAnother} className="px-5 py-2.5 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all">
              Upload Another
            </button>
            <button onClick={onGoToChat} className="px-5 py-2.5 text-[0.8125rem] font-medium bg-transparent border border-border-strong text-silver rounded-md hover:bg-white/[0.04] transition-colors">
              Go to Chat
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
