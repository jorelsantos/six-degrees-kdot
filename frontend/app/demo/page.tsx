import { ShowcaseGrid } from "./components/showcase-grid";

export const metadata = {
  title: "Rabbit Hole — Demo",
};

export default function DemoLanding() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-16">
      <div className="text-center">
        <p className="text-caption uppercase tracking-[0.1em] text-brand">
          Six degrees of Kendrick Lamar — demo
        </p>
        <h1 className="mt-3 text-display font-black tracking-tight sm:text-displayLg">
          Pick an artist
        </h1>
        <p className="mx-auto mt-3 max-w-md text-content-secondary">
          A preview of Rabbit Hole with a curated set of artists — no live search here,
          just click a face and see how close they are to Kendrick.
        </p>
      </div>

      <div className="mt-10">
        <ShowcaseGrid />
      </div>
    </div>
  );
}
