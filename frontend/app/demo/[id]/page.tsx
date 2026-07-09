import { DemoChainView } from "./demo-chain-view";

export default async function DemoChainPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <DemoChainView artistId={id} />;
}
