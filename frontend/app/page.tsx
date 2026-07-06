import { SearchTypeahead } from "./components/search-typeahead";

export default function Home() {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-2xl flex-col items-center justify-center px-6 py-16 text-center">
      <p className="text-caption uppercase tracking-[0.1em] text-brand">
        Six degrees of Kendrick Lamar
      </p>
      <h1 className="mt-3 text-display font-black tracking-tight sm:text-displayLg">
        Rabbit Hole
      </h1>
      <p className="mt-3 max-w-md text-content-secondary">
        Type any artist and find their shortest collaboration path to Kendrick Lamar.
      </p>

      <div className="mt-10 w-full text-left">
        <SearchTypeahead />
      </div>
    </div>
  );
}
