// SOH gauge: 240° arc from 40 % to 100 %, the calibrated 90 % interval drawn as a band,
// the estimate as a needle, and screening thresholds as ticks.
const MIN = 40, MAX = 100, START = 150, SWEEP = 240;

function pt(cx: number, cy: number, r: number, deg: number) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function arc(cx: number, cy: number, r: number, from: number, to: number) {
  const [x1, y1] = pt(cx, cy, r, from), [x2, y2] = pt(cx, cy, r, to);
  return `M ${x1} ${y1} A ${r} ${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x2} ${y2}`;
}
const ang = (v: number) => START + ((Math.max(MIN, Math.min(MAX, v)) - MIN) / (MAX - MIN)) * SWEEP;

export default function Gauge({ soh, lo, hi, size = 240 }: { soh: number; lo: number; hi: number; size?: number }) {
  const cx = 120, cy = 120, r = 96;
  const [nx, ny] = pt(cx, cy, r - 18, ang(soh));
  const color = soh >= 80 ? "#B6F23A" : soh >= 65 ? "#4FC3E0" : "#F2B33D";
  return (
    <svg viewBox="0 0 240 210" width={size} height={size * 0.875} role="img" aria-label={`State of health ${soh.toFixed(1)} percent, interval ${lo.toFixed(1)} to ${hi.toFixed(1)}`}>
      <path d={arc(cx, cy, r, START, START + SWEEP)} stroke="#1F2E4A" strokeWidth="14" fill="none" strokeLinecap="round" />
      <path d={arc(cx, cy, r, START, ang(soh))} stroke={color} strokeWidth="14" fill="none" strokeLinecap="round" opacity="0.9" />
      <path d={arc(cx, cy, r + 13, ang(lo), Math.max(ang(hi), ang(lo) + 0.5))} stroke="#E8EEF7" strokeOpacity="0.55" strokeWidth="4" fill="none" />
      {[60, 70, 80, 90].map((t) => {
        const [x1, y1] = pt(cx, cy, r - 10, ang(t)), [x2, y2] = pt(cx, cy, r + 8, ang(t)), [lx, ly] = pt(cx, cy, r - 24, ang(t));
        return (
          <g key={t}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#0E1726" strokeWidth="2" />
            <text x={lx} y={ly + 3} textAnchor="middle" fontSize="9" fill="#66779A">{t}</text>
          </g>
        );
      })}
      <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="#E8EEF7" strokeWidth="2" strokeLinecap="round" />
      <circle cx={cx} cy={cy} r="4" fill="#E8EEF7" />
      <text x={cx} y={cy + 44} textAnchor="middle" className="font-display-tight" fontSize="34" fontWeight="700" fill="#E8EEF7">{soh.toFixed(1)}%</text>
      <text x={cx} y={cy + 62} textAnchor="middle" fontSize="10.5" fill="#8A9AB5">90% interval {lo.toFixed(1)}–{hi.toFixed(1)}%</text>
    </svg>
  );
}
