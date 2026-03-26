interface FileChipProps {
  name: string;
  onRemove: () => void;
}

export default function FileChip({ name, onRemove }: FileChipProps) {
  return (
    <span className="inline-flex items-center gap-1.5 bg-surface border border-border-strong rounded px-2.5 py-1 text-xs text-silver m-0.5">
      {name}
      <span
        onClick={(e) => { e.stopPropagation(); onRemove(); }}
        className="cursor-pointer text-mid font-semibold hover:text-rose transition-colors"
      >
        &times;
      </span>
    </span>
  );
}
