import { Composition } from 'remotion';
import { SubtitleOverlay } from './SubtitleOverlay';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SubtitleOverlay"
    component={SubtitleOverlay}
    durationInFrames={900}
    fps={30}
    width={1920}
    height={1080}
    defaultProps={{
      videoSrc: '',
      subtitles: [],
      translatedSubtitles: [],
    }}
  />
);
