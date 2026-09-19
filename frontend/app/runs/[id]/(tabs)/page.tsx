import { MapScreen } from "@/components/run/MapScreen";

export function generateStaticParams() {
  return [{ id: "mock" }];
}

export default function Page() {
  return <MapScreen />;
}
