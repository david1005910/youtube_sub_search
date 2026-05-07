import { AbsoluteFill, OffthreadVideo, useCurrentFrame, useVideoConfig } from 'remotion';

export type SubtitleSegment = {
  text: string;
  start: number;   // seconds
  duration: number;
};

export type SubtitleOverlayProps = {
  videoSrc: string;
  subtitles: SubtitleSegment[];
  translatedSubtitles?: SubtitleSegment[];
};

const subtitleStyle: React.CSSProperties = {
  color: '#FFFFFF',
  fontSize: 38,
  fontWeight: 700,
  fontFamily: 'Noto Sans KR, Malgun Gothic, sans-serif',
  textShadow: '2px 2px 6px #000, -2px -2px 6px #000, 0 0 12px #000',
  lineHeight: 1.4,
};

const translatedStyle: React.CSSProperties = {
  ...subtitleStyle,
  color: '#FFE066',
  fontSize: 30,
  marginBottom: 8,
};

export const SubtitleOverlay: React.FC<SubtitleOverlayProps> = ({
  videoSrc,
  subtitles,
  translatedSubtitles = [],
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const cur = subtitles.find(s => t >= s.start && t < s.start + s.duration);
  const curTr = translatedSubtitles.find(s => t >= s.start && t < s.start + s.duration);

  return (
    <AbsoluteFill>
      <OffthreadVideo src={videoSrc} />
      {(cur || curTr) && (
        <div
          style={{
            position: 'absolute',
            bottom: 72,
            left: 0,
            right: 0,
            textAlign: 'center',
            padding: '0 60px',
          }}
        >
          {curTr && <div style={translatedStyle}>{curTr.text}</div>}
          {cur && <div style={subtitleStyle}>{cur.text}</div>}
        </div>
      )}
    </AbsoluteFill>
  );
};
