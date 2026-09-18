import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Voice & screen notes — MediaRecorder wrapper.
 *
 * `start("voice")` captures the microphone; `start("screen")` captures the
 * display (with mic mixing when the browser offers it via getDisplayMedia's
 * `audio` hint). On stop, the recording is handed to `onComplete(blob, label)`
 * — LivePaste uploads it through the regular any-file endpoint so it behaves
 * like any other attachment (and syncs to every viewer).
 *
 * The stream is ALWAYS fully stopped (every track) on cancel/unmount so the
 * screen-share indicator disappears immediately.
 */
export function useRecorder({ onComplete }) {
  const [recording, setRecording] = useState(null); // null | "voice" | "screen"
  const [seconds, setSeconds] = useState(0);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const stopStream = useCallback(() => {
    const stream = streamRef.current;
    if (stream) {
      for (const track of stream.getTracks()) track.stop();
      streamRef.current = null;
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (kind) => {
      if (recorderRef.current) return;
      let stream;
      try {
        if (kind === "screen") {
          // Mobile browsers (iOS Safari, Android Chrome) don't offer display
          // capture — surface that cleanly instead of throwing deep inside.
          if (!navigator.mediaDevices || typeof navigator.mediaDevices.getDisplayMedia !== "function") {
            return "unsupported";
          }
          stream = await navigator.mediaDevices.getDisplayMedia({
            video: { frameRate: 15 },
            audio: true, // browser may offer tab/system audio
          });
          // Optionally mix the microphone in, when permitted
          try {
            const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
            for (const track of mic.getAudioTracks()) stream.addTrack(track);
          } catch {
            /* mic denied — screen-only recording is fine */
          }
        } else {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        }
      } catch {
        return "denied";
      }
      streamRef.current = stream;
      chunksRef.current = [];
      // iOS Safari can't produce webm — it records AAC in an MP4 container;
      // Firefox mobile offers ogg/opus. Pick the first the browser supports.
      const mimeCandidates = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4", // iOS Safari
        "audio/ogg;codecs=opus", // Firefox
        "video/webm;codecs=vp8,opus",
        "video/webm",
      ];
      const mimeType = mimeCandidates.find((m) => {
        try {
          return MediaRecorder.isTypeSupported(m);
        } catch {
          return false;
        }
      });
      let rec;
      try {
        rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      } catch {
        stopStream();
        return "unsupported";
      }
      recorderRef.current = rec;
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        chunksRef.current = [];
        recorderRef.current = null;
        stopStream();
        setRecording(null);
        setSeconds(0);
        if (blob.size > 0 && onCompleteRef.current) {
          onCompleteRef.current(blob, kind === "screen" ? "screen-note" : "voice-note");
        }
      };
      // ANY track ending (user clicks the browser's "Stop sharing", mic is
      // unplugged, OS revokes permission) finishes the recording cleanly —
      // previously only the screen video track was watched, so a voice note
      // whose mic track died silently produced an empty/unusable file.
      const onTrackEnded = () => {
        if (recorderRef.current === rec && rec.state !== "inactive") rec.stop();
      };
      for (const track of stream.getTracks()) track.addEventListener("ended", onTrackEnded);
      rec.start(1000); // 1s chunks keep memory flat on long notes
      setRecording(kind);
      setSeconds(0);
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
      return "recording";
    },
    [stopStream],
  );

  const stop = useCallback(() => {
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
  }, []);

  const cancel = useCallback(() => {
    const rec = recorderRef.current;
    if (rec) {
      rec.onstop = null; // drop the captured chunks
      if (rec.state !== "inactive") rec.stop();
      recorderRef.current = null;
    }
    stopStream();
    setRecording(null);
    setSeconds(0);
  }, [stopStream]);

  // Safety net: never leave a capture running when the page goes away
  useEffect(
    () => () => {
      cancel();
    },
    [cancel],
  );

  return { recording, seconds, start, stop, cancel };
}
