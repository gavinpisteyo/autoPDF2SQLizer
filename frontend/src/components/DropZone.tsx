import { useCallback, useRef, useState } from 'react';

interface DropZoneProps {
  accept?: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  children?: React.ReactNode;
}

export default function DropZone({ accept = '.pdf', multiple = false, onFiles, children }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) {
      onFiles(Array.from(e.dataTransfer.files));
    }
  }, [onFiles]);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) {
      onFiles(Array.from(e.target.files));
      e.target.value = '';
    }
  }, [onFiles]);

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`
        border-[1.5px] border-dashed rounded-lg p-8 text-center cursor-pointer
        transition-all duration-200 mb-5
        ${dragging
          ? 'border-coral bg-coral/[0.08] text-silver'
          : 'border-charcoal text-mid hover:border-coral hover:bg-coral/[0.08] hover:text-silver'
        }
      `}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={handleChange}
        className="hidden"
      />
      {children || (
        <p className="text-[0.8125rem] font-light">
          Drop files here or <strong className="font-medium text-silver">click to browse</strong>
        </p>
      )}
    </div>
  );
}
