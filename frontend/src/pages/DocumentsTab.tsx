import { useState } from 'react';
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

interface SchemaProperties {
  [key: string]: {
    type?: string;
    items?: SchemaProperties;
    properties?: Record<string, SchemaProperties>;
    [k: string]: unknown;
  };
}

export default function DocumentsTab({ api, onGoToChat }: DocumentsTabProps) {
  const workflow = useDocumentWorkflow();
  const [extractionStatus, setExtractionStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });
  const [saving, setSaving] = useState(false);
  const [schemaProperties, setSchemaProperties] = useState<SchemaProperties>({});

  const handleProjectSelected = (project: ProjectInfo) => {
    workflow.selectProject(project);

    // Try to load the project schema for later use in results table
    if (project.id) {
      api.getProjectSchema(project.id)
        .then((data: { schema?: { properties?: SchemaProperties } }) => {
          if (data.schema?.properties) {
            setSchemaProperties(data.schema.properties);
          }
        })
        .catch(() => {});
    }
  };

  const handleSchemaGenerated = (docTypeKey: string, schema: Record<string, unknown>, projectId: string) => {
    workflow.setSchemaGenerated(docTypeKey, schema, projectId);
    const props = (schema as { properties?: SchemaProperties }).properties;
    if (props) {
      setSchemaProperties(props);
    }
  };

  const handleUploadSubmit = async (pdfFile: File, groundTruthFile?: File) => {
    if (!workflow.selectedProject?.id) return;

    workflow.startExtraction();
    setExtractionStatus({ msg: 'Extracting document...', type: 'loading' });

    try {
      const data = await api.uploadDocument(workflow.selectedProject.id, pdfFile, groundTruthFile);

      if (data.schema?.properties) {
        setSchemaProperties(data.schema.properties as SchemaProperties);
      }

      if (data.extracted) {
        workflow.setExtractionResults(data.extracted as Record<string, unknown>, data.source_file as string || '');
        setExtractionStatus({ msg: 'Extraction complete. Review the results below.', type: 'success' });
      } else {
        setExtractionStatus({ msg: data.message as string || 'Extraction completed', type: 'success' });
        workflow.completeOptimization();
      }
    } catch (e: unknown) {
      setExtractionStatus({ msg: e instanceof Error ? e.message : 'Extraction failed', type: 'error' });
      workflow.goToUpload();
    }
  };

  const handleSaveCorrections = async (correctedData: Record<string, unknown>) => {
    if (!workflow.selectedProject?.id) return;

    setSaving(true);
    try {
      const result = await api.saveCorrections(
        workflow.selectedProject.id,
        workflow.sourceFile,
        workflow.docTypeKey,
        correctedData,
      );

      // Start background optimization if applicable
      if (result.optimization_started) {
        workflow.startOptimization(result.run_id as string || '');
      } else {
        workflow.completeOptimization();
      }
    } catch (e: unknown) {
      setExtractionStatus({ msg: e instanceof Error ? e.message : 'Save failed', type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const handleStartOptimization = async () => {
    if (!workflow.selectedProject?.id) return;
    try {
      const result = await api.startBackgroundOptimization(workflow.selectedProject.id);
      workflow.startOptimization(result.run_id as string || '');
    } catch (e: unknown) {
      setExtractionStatus({ msg: e instanceof Error ? e.message : 'Failed to start optimization', type: 'error' });
    }
  };

  return (
    <div>
      {/* Back button when not at project selection */}
      {workflow.workflowState !== 'SELECT_PROJECT' && (
        <button
          onClick={workflow.reset}
          className="mb-5 text-[0.8125rem] text-mid hover:text-silver transition-colors"
        >
          &larr; Back to projects
        </button>
      )}

      {/* Project name header when a project is selected */}
      {workflow.selectedProject && workflow.workflowState !== 'SELECT_PROJECT' && (
        <div className="mb-5 pb-4 border-b border-border">
          <h2 className="font-heading text-lg font-semibold text-cloud tracking-tight">
            {workflow.selectedProject.name}
          </h2>
        </div>
      )}

      {/* SELECT_PROJECT */}
      {workflow.workflowState === 'SELECT_PROJECT' && (
        <ProjectSelector
          api={api}
          onProjectSelected={handleProjectSelected}
          onCreateNew={workflow.startCreateProject}
        />
      )}

      {/* DEFINE_SCHEMA */}
      {workflow.workflowState === 'DEFINE_SCHEMA' && workflow.selectedProject && (
        <SchemaGenerator
          api={api}
          projectName={workflow.selectedProject.name}
          onSchemaGenerated={handleSchemaGenerated}
        />
      )}

      {/* UPLOAD */}
      {workflow.workflowState === 'UPLOAD' && workflow.selectedProject && (
        <UploadArea
          onSubmit={handleUploadSubmit}
          projectName={workflow.selectedProject.name}
        />
      )}

      {/* EXTRACTING */}
      {workflow.workflowState === 'EXTRACTING' && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="w-3 h-3 rounded-full bg-coral animate-pulse mb-4" />
          <p className="text-[0.8125rem] text-silver mb-2">Extracting document...</p>
          <p className="text-[0.6875rem] text-mid">This may take a moment.</p>
          <StatusMessage message={extractionStatus.msg} type={extractionStatus.type} />
        </div>
      )}

      {/* REVIEW_RESULTS */}
      {workflow.workflowState === 'REVIEW_RESULTS' && workflow.extractionResults && (
        <div>
          <StatusMessage message={extractionStatus.msg} type={extractionStatus.type} />
          <div className="mt-4">
            <ResultsTable
              data={workflow.extractionResults}
              schema={schemaProperties}
              onSave={handleSaveCorrections}
              saving={saving}
            />
          </div>
        </div>
      )}

      {/* OPTIMIZING */}
      {workflow.workflowState === 'OPTIMIZING' && (
        <OptimizationBanner
          api={api}
          onComplete={workflow.completeOptimization}
          onGoToChat={onGoToChat}
        />
      )}

      {/* COMPLETE */}
      {workflow.workflowState === 'COMPLETE' && (
        <div className="text-center py-12">
          <div className="w-12 h-12 rounded-full bg-sage-bg flex items-center justify-center mx-auto mb-4">
            <div className="w-3 h-3 rounded-full bg-sage" />
          </div>
          <h2 className="font-heading text-lg font-semibold text-cloud tracking-tight mb-2">
            Document Processed
          </h2>
          <p className="text-[0.8125rem] text-mid font-light mb-6">
            Your data has been extracted and saved. You can query it in Chat or upload more documents.
          </p>
          <div className="flex gap-3 justify-center">
            <button
              onClick={workflow.uploadAnother}
              className="px-5 py-2.5 text-[0.8125rem] font-medium bg-coral text-white rounded-md
                         hover:bg-coral-muted active:translate-y-px transition-all"
            >
              Upload Another
            </button>
            <button
              onClick={onGoToChat}
              className="px-5 py-2.5 text-[0.8125rem] font-medium bg-transparent border border-border-strong text-silver rounded-md
                         hover:bg-white/[0.04] transition-colors"
            >
              Go to Chat
            </button>
            {workflow.selectedProject && !workflow.selectedProject.is_optimized && (
              <button
                onClick={handleStartOptimization}
                className="px-5 py-2.5 text-[0.8125rem] font-medium bg-transparent border border-coral/30 text-coral rounded-md
                           hover:bg-coral/[0.08] transition-colors"
              >
                Optimize Extraction
              </button>
            )}
          </div>
        </div>
      )}

      {/* READY (subsequent uploads, project already has data) */}
      {workflow.workflowState === 'READY' && workflow.selectedProject && (
        <UploadArea
          onSubmit={handleUploadSubmit}
          projectName={workflow.selectedProject.name}
        />
      )}
    </div>
  );
}
