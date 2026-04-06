import { fetchOpportunities } from "@/lib/api";
import { DashboardClient } from "./components/dashboard/DashboardClient";

export default async function DashboardPage() {
  let data;
  try {
    data = await fetchOpportunities();
  } catch {
    return (
      <main className="flex items-center justify-center h-[80vh]">
        <div className="font-mono text-xs text-center" style={{ color: "#374151" }}>
          <p style={{ color: "#ef4444" }}>● CONNECTION ERROR</p>
          <p className="mt-2">Backend unreachable on port 8000</p>
          <p className="mt-1 text-[10px]" style={{ color: "#374151" }}>
            Check ODDS_API_KEY is set and uvicorn is running
          </p>
        </div>
      </main>
    );
  }

  return <DashboardClient initialData={data} />;
}
