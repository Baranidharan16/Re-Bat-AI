import { lazy, Suspense, type ComponentProps } from "react";

const BatteryTwin3D = lazy(() => import("./BatteryTwin3D"));

/** three.js is loaded only when a 3D view is on screen (keeps the first page fast). */
export default function LazyTwin(props: ComponentProps<typeof BatteryTwin3D>) {
  return (
    <Suspense fallback={<div className="panel flex items-center justify-center gap-3 text-sm text-fog-400" style={{ height: props.height ?? 560 }}><span className="h-2 w-2 rounded-full bg-volt live-dot" />Loading 3D battery…</div>}>
      <BatteryTwin3D {...props} />
    </Suspense>
  );
}
