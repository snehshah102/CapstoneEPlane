import { PlaneDashboard } from "@/components/plane/plane-dashboard";

export default async function PlaneDashboardPage({
  params
}: {
  params: Promise<{ planeId: string }>;
}) {
  const { planeId } = await params;
  return <PlaneDashboard planeId={planeId} />;
}
