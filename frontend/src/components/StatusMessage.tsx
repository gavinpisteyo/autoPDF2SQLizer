type StatusType = 'success' | 'error' | 'loading' | null;

interface StatusMessageProps {
  message: string;
  type: StatusType;
}

const styles: Record<string, string> = {
  success: 'bg-sage-bg text-sage',
  error: 'bg-rose-bg text-rose',
  loading: 'bg-white/[0.04] text-silver',
};

export default function StatusMessage({ message, type }: StatusMessageProps) {
  if (!message || !type) return null;

  return (
    <div className={`px-3 py-2 rounded-[5px] text-[0.8125rem] mt-4 ${styles[type] || ''}`}>
      {message}
    </div>
  );
}
