// recharts 里用的「半透明数值 Badge」。
// HTML 的 Badge 组件在 recharts 的 SVG 内不渲染,只能自绘 rect + text 画同款外观。
export const DOT_RADIUS = 4;
export const BADGE_HEIGHT = 18;
export const BADGE_GAP = 6;
const BADGE_FONT_SIZE = 11;
const BADGE_PADDING_X = 7;
/** Badge 底色透明度:压到 0.55,底下的线才明显透得出来;调这一个值就能控制「通透 ↔ 可读」 */
const BADGE_FILL_OPACITY = 0.55;

/**
 * Badge 落点相对点位的关系。
 * 最右端的点必须走左侧预设:居中挂点会被容器右边界裁掉。
 * 左上/左下两个预设供同一 x 上的多条线各挂一个,一上一下即使两线重合也不互相压住。
 */
export type BadgeAlign = 'top' | 'left' | 'upper-left' | 'lower-left';

/** Badge 宽度估算:SVG 的 rect 没有自动布局,只能按字数估(CJK 记 1 个字宽、ASCII 记 0.6) */
export function badgeWidth(text: string, fontSize: number): number {
  let units = 0;
  for (const char of text) {
    units += /[\u4e00-\u9fff]/.test(char) ? 1 : 0.6;
  }
  return Math.ceil(units * fontSize) + BADGE_PADDING_X * 2;
}

/**
 * 药丸 + 居中白字(没有圆点):给「没有点位可挂」的标注文字加底。
 * 柱状图的标线就是这类——文字直接画在柱子上会互相干扰,垫一层内缩的底色才读得出。
 */
export function TextBadge({
  x,
  y,
  tone,
  text,
  /** x 的含义:默认是药丸**左边界**;传 'center' 时 x 是**中心点**(把药丸骑在虚线上用) */
  anchor = 'left',
  /**
   * 底色透明度:默认沿用彩色 Badge 的 0.55(要线透出来)。
   * 灰底 + 白字时不能这么透——0.55 压在白底上最深只能到 #737373,那只有拿纯黑做底
   * 才做得到,于是又变成「黑色降透明度」;这类标注要显式调高。
   */
  fillOpacity = BADGE_FILL_OPACITY,
}: {
  x: number;
  y: number;
  tone: string;
  text: string;
  anchor?: 'left' | 'center';
  fillOpacity?: number;
}) {
  const width = badgeWidth(text, BADGE_FONT_SIZE);
  const left = anchor === 'center' ? x - width / 2 : x;
  return (
    <g>
      <rect
        x={left}
        y={y}
        width={width}
        height={BADGE_HEIGHT}
        rx={BADGE_HEIGHT / 2}
        fill={tone}
        fillOpacity={fillOpacity}
      />
      <text
        x={left + width / 2}
        y={y + BADGE_HEIGHT / 2}
        fill="#fff"
        fontSize={BADGE_FONT_SIZE}
        fontWeight={500}
        textAnchor="middle"
        dominantBaseline="central"
      >
        {text}
      </text>
    </g>
  );
}

/**
 * 圆点 + 半透明语义色 Badge(白字)。
 * 白字不再与线段同色,线穿过时字仍可读;底半透明则线能透出来。
 */
export function DotWithBadge({
  cx = 0,
  cy = 0,
  tone,
  text,
  align = 'top',
}: {
  cx?: number;
  cy?: number;
  tone: string;
  text: string;
  align?: BadgeAlign;
}) {
  const width = badgeWidth(text, BADGE_FONT_SIZE);
  const badgeX =
    align === 'top' ? cx - width / 2 : cx - DOT_RADIUS - BADGE_GAP - width;
  const badgeY =
    align === 'top' || align === 'upper-left'
      ? cy - DOT_RADIUS - BADGE_GAP - BADGE_HEIGHT
      : align === 'lower-left'
        ? cy + DOT_RADIUS + BADGE_GAP
        : cy - BADGE_HEIGHT / 2;
  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={DOT_RADIUS}
        fill={tone}
        stroke="var(--card)"
        strokeWidth={1.5}
      />
      <TextBadge x={badgeX} y={badgeY} tone={tone} text={text} />
    </g>
  );
}
