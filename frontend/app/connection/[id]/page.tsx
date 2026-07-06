import { ConnectionView } from "@/app/components/connection-view";

// Next 16: params and searchParams are async. The heavy lifting (fetch, states)
// lives in the client component; this server component just unwraps the route.
export default async function ConnectionPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ notice?: string }>;
}) {
  const { id } = await params;
  const { notice } = await searchParams;
  return <ConnectionView artistId={id} showNotice={notice === "1"} />;
}
