import {
  Activity,
  GitCompareArrows,
  LayoutDashboard,
  ListChecks,
  Pin,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { NavLink, useLocation } from "react-router";
import { useHealth } from "@/api/queries";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

export const NAV: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/runs", label: "Runs", icon: ListChecks },
  { to: "/compare", label: "Compare", icon: GitCompareArrows },
  { to: "/trends", label: "Trends & drift", icon: Activity },
  { to: "/baselines", label: "Baselines & prompts", icon: Pin },
];

export function isActive(to: string, pathname: string): boolean {
  return to === "/" ? pathname === "/" : pathname === to || pathname.startsWith(`${to}/`);
}

function HealthDot() {
  const { data, isError } = useHealth();
  const ok = data?.status === "ok" && !isError;
  const label = isError
    ? "Server not reachable"
    : !data
      ? "Connecting…"
      : ok
        ? `${data.runs} runs recorded`
        : "History database unavailable";
  return (
    <div className="flex items-center gap-2 px-2 text-xs text-muted-foreground" role="status">
      <span
        aria-hidden
        className={cn(
          "size-2 rounded-full",
          !data && !isError ? "bg-muted-foreground/40" : ok ? "bg-pass" : "bg-error",
        )}
      />
      <span className="truncate group-data-[collapsible=icon]:hidden">{label}</span>
    </div>
  );
}

export function AppSidebar() {
  const { pathname } = useLocation();
  const { data } = useHealth();
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <NavLink to="/">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <ShieldCheck className="size-4" aria-hidden />
                </div>
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate font-semibold">RegressionGuard</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {data?.app ?? "…"}
                  </span>
                </div>
              </NavLink>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map(({ to, label, icon: Icon }) => (
                <SidebarMenuItem key={to}>
                  <SidebarMenuButton asChild isActive={isActive(to, pathname)} tooltip={label}>
                    <NavLink to={to} end={to === "/"}>
                      <Icon aria-hidden />
                      <span>{label}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <HealthDot />
        {data && (
          <p className="px-2 text-[11px] text-muted-foreground/70 group-data-[collapsible=icon]:hidden">
            v{data.version} · local, read-only
          </p>
        )}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
