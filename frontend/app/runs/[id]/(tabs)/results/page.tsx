import { ResultsScreen } from "@/components/run/ResultsScreen";

export function generateStaticParams() {
  return [{ id: "mock" }];
}

export default function Page() {
  return <ResultsScreen />;
}
