import { SwarmScreen } from "@/components/run/screens";

export function generateStaticParams() {
  return [{ id: "mock" }];
}

export default function Page() {
  return <SwarmScreen />;
}
