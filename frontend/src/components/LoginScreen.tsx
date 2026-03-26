import { useAuthContext } from '../lib/auth';

export default function LoginScreen() {
  const { login, isLoading } = useAuthContext();

  return (
    <div className="min-h-[100dvh] flex items-center justify-center">
      <div className="text-center max-w-sm">
        <h1 className="font-heading text-2xl font-semibold text-cloud tracking-tight mb-1">
          autoPDF2SQLizer
        </h1>
        <p className="text-coral text-sm font-medium mb-8">by Pisteyo</p>

        <p className="text-mid text-sm font-light mb-8 leading-relaxed">
          Extract structured data from documents.<br />
          Build accuracy. Push to your database.
        </p>

        <button
          onClick={login}
          disabled={isLoading}
          className="w-full px-6 py-3 text-sm font-medium bg-coral text-white rounded-lg
                     hover:bg-coral-muted active:translate-y-px transition-all
                     disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {isLoading ? 'Loading...' : 'Sign In'}
        </button>
      </div>
    </div>
  );
}
