import { useState } from 'react';
import DropZone from './DropZone';

interface UploadAreaProps {
  onSubmit: (pdfFile: File, groundTruthFile?: File) => void;
  disabled?: boolean;
  projectName: string;
}

export default function UploadArea({ onSubmit, disabled = false, projectName }: UploadAreaProps) {
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [hasExample, setHasExample] = useState(false);
  const [groundTruthFile, setGroundTruthFile] = useState<File | null>(null);

  const handlePdfFiles = (files: File[]) => {
    const pdf = files.find(f => f.name.toLowerCase().endsWith('.pdf'));
    if (pdf) setPdfFile(pdf);
  };

  const handleGtFiles = (files: File[]) => {
    const json = files.find(f => f.name.toLowerCase().endsWith('.json'));
    if (json) setGroundTruthFile(json);
  };

  const handleSubmit = () => {
    if (!pdfFile) return;
    onSubmit(pdfFile, hasExample && groundTruthFile ? groundTruthFile : undefined);
  };

  return (
    <div>
      <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">
        Upload Document
      </h2>
      <p className="text-[0.8125rem] text-mid font-light mb-5">
        Upload a PDF to extract data for <span className="text-silver font-medium">{projectName}</span>.
      </p>

      {/* PDF Drop Zone */}
      <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
        PDF Document
      </label>
      <DropZone accept=".pdf" onFiles={handlePdfFiles}>
        <p className="text-[0.8125rem] font-light">
          {pdfFile ? (
            <span className="text-silver font-medium">{pdfFile.name}</span>
          ) : (
            <>Drop a PDF here or <strong className="font-medium text-silver">click to browse</strong></>
          )}
        </p>
      </DropZone>

      {/* Ground truth toggle */}
      <label className="flex items-center gap-2 cursor-pointer text-[0.8125rem] text-silver mb-5">
        <input
          type="checkbox"
          checked={hasExample}
          onChange={(e) => {
            setHasExample(e.target.checked);
            if (!e.target.checked) setGroundTruthFile(null);
          }}
          className="accent-coral"
        />
        I have an example output for this document
      </label>

      {/* Ground truth drop zone */}
      {hasExample && (
        <div className="mb-5">
          <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
            Example Output (JSON)
          </label>
          <DropZone accept=".json" onFiles={handleGtFiles}>
            <p className="text-[0.8125rem] font-light">
              {groundTruthFile ? (
                <span className="text-silver font-medium">{groundTruthFile.name}</span>
              ) : (
                <>Drop a JSON file or <strong className="font-medium text-silver">click to browse</strong></>
              )}
            </p>
          </DropZone>
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={disabled || !pdfFile}
        className="px-5 py-2.5 text-[0.8125rem] font-medium bg-coral text-white rounded-md
                   hover:bg-coral-muted active:translate-y-px transition-all
                   disabled:opacity-30 disabled:cursor-not-allowed"
      >
        Extract Document
      </button>
    </div>
  );
}
