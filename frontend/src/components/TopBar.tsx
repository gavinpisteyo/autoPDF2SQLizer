import { useAuthContext } from '../lib/auth';

type TabId = 'projects' | 'chat';

interface TopBarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  onProfileClick: () => void;
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'projects', label: 'Projects' },
  { id: 'chat', label: 'Chat' },
];

export default function TopBar({ activeTab, onTabChange, onProfileClick }: TopBarProps) {
  const { user } = useAuthContext();

  return (
    <div className="mb-10">
      {/* Row 1: Brand */}
      <div className="flex items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <h1 className="font-heading text-xl font-semibold tracking-tight text-cloud">
            autoPDF2SQLizer <span className="font-normal text-coral">by Pisteyo</span>
          </h1>
          <p className="text-[0.8125rem] text-mid mt-1 font-light tracking-wide">
            Extract structured data from documents. Build accuracy. Push to your database.
          </p>
        </div>

        {/* Profile avatar */}
        {user && (
          <button
            onClick={onProfileClick}
            className="flex items-center gap-2 flex-shrink-0 hover:opacity-80 transition-opacity"
            title="Profile"
          >
            {user.picture ? (
              <img src={user.picture} alt="" className="w-8 h-8 rounded-full" />
            ) : (
              <div className="w-8 h-8 rounded-full bg-charcoal flex items-center justify-center">
                <span className="text-sm font-heading font-semibold text-cloud">
                  {(user.name || '?')[0].toUpperCase()}
                </span>
              </div>
            )}
          </button>
        )}
      </div>

      {/* Row 2: Tab navigation */}
      <nav className="flex justify-center border-b border-border">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`
              px-6 py-3 text-[0.8125rem] font-medium border-b-[1.5px] -mb-px transition-colors
              ${activeTab === tab.id
                ? 'text-cloud border-coral'
                : 'text-mid border-transparent hover:text-silver'
              }
            `}
          >
            {tab.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
