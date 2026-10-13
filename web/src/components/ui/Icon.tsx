import {
  BookOpen, Bot, ChevronDown, CloudSun, Cpu, Database, FileText, Globe2, Inbox, Info, LayoutDashboard, MapPin, Menu, Newspaper, Orbit, RefreshCw, SlidersHorizontal,
  TriangleAlert, Waves, Wind, X, type LucideIcon,
} from "lucide-react";

// One icon set (Lucide) for the whole app. The names are the ones the navigation and states already use.
const ICONS: Record<string, LucideIcon> = {
  overview: LayoutDashboard,
  weather: CloudSun,
  air: Wind,
  atmosphere: Waves,
  twin: Globe2,
  flow: Orbit,
  database: Database,
  article: Newspaper,
  assistant: Bot,
  knowledge: BookOpen,
  reports: FileText,
  training: Cpu,
  settings: SlidersHorizontal,
  menu: Menu,
  close: X,
  info: Info,
  alert: TriangleAlert,
  refresh: RefreshCw,
  chevron: ChevronDown,
  pin: MapPin,
  inbox: Inbox,
};

export function Icon({ name, className = "h-5 w-5" }: { name: string; className?: string }) {
  const Cmp = ICONS[name] ?? Info;
  return <Cmp className={className} strokeWidth={1.75} aria-hidden="true" />;
}
