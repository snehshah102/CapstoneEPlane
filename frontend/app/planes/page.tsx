import { PlaneIndex } from "@/components/plane/plane-index";
import { getLivePlanesPayload } from "@/lib/live-plane-summaries";

export const dynamic = "force-dynamic";

export default async function PlanesPage() {
  const initialData = await getLivePlanesPayload();
  return <PlaneIndex initialPlanes={initialData.planes} />;
}
