import { fetchSnapshot } from "@/lib/api";
import { DashboardClient } from "./components/dashboard/DashboardClient";

export default async function DashboardPage() {
  // Try to load a cached snapshot (read-only, instant).
  // If no snapshot exists or backend is unreachable, pass null —
  // the client component will fetch on mount. Never block on pipeline.
  let data = null;
  try {
    data = await fetchSnapshot();
  } catch {
    // Backend unreachable — client will retry on mount
  }

  return <DashboardClient initialData={data} />;
}
