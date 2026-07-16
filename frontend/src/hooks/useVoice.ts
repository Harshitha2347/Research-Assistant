import { useCallback, useEffect, useRef, useState } from "react";



type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function useVoice() {
  const RecognitionCtor = getSpeechRecognitionCtor();
  const sttSupported = !!RecognitionCtor;
  const ttsSupported = typeof window !== "undefined" && "speechSynthesis" in window;

  const [listening, setListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(false);
  const [voiceError, setVoiceError] = useState("");

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const onFinalRef = useRef<((text: string) => void) | null>(null);

  const startListening = useCallback(
    (onFinalTranscript: (text: string) => void) => {
      if (!RecognitionCtor) {
        setVoiceError("Speech-to-text isn't supported in this browser — try Chrome or Edge.");
        return;
      }
      
      if (typeof window !== "undefined" && window.isSecureContext === false) {
        setVoiceError("Voice input needs a secure (https) connection to work — it won't record over plain http.");
        return;
      }

      
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch {
          
        }
        recognitionRef.current = null;
      }

      setVoiceError("");
      onFinalRef.current = onFinalTranscript;

      const recognition = new RecognitionCtor();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onresult = (event: any) => {
        let interim = "";
        let final = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) final += transcript;
          else interim += transcript;
        }
        setInterimTranscript(interim);
        if (final) onFinalRef.current?.(final.trim());
      };

      recognition.onerror = (event: any) => {
        
        const messages: Record<string, string> = {
          "not-allowed": "Microphone access was denied — allow it in your browser's site settings and try again.",
          "service-not-allowed": "Microphone access was blocked by the browser — check your site permissions and try again.",
          "no-speech": "Didn't catch any speech — press the mic and start talking right away.",
          "audio-capture": "No microphone was found — check that one is connected and not in use by another app.",
          network: "Voice recognition needs an internet connection — check your connection and try again.",
        };
        const msg = messages[event?.error];
       
        if (event?.error !== "aborted") {
          setVoiceError(msg ?? "Voice input hit a snag — please try again.");
        }
        setListening(false);
        recognitionRef.current = null;
      };

      recognition.onend = () => {
        setListening(false);
        setInterimTranscript("");
        recognitionRef.current = null;
      };

      recognitionRef.current = recognition;
      try {
        recognition.start();
        setListening(true);
      } catch {
        
        setVoiceError("Couldn't start the microphone — please wait a moment and try again.");
        setListening(false);
        recognitionRef.current = null;
      }
    },
    [RecognitionCtor]
  );

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setListening(false);
  }, []);

  const speak = useCallback(
    (text: string) => {
      if (!ttsSupported || !text.trim()) return;
      window.speechSynthesis.cancel();
      
      const clean = text.replace(/\*\*([^*]+)\*\*/g, "$1");
      const utterance = new SpeechSynthesisUtterance(clean);
      utterance.rate = 1.0;
      utterance.onstart = () => setSpeaking(true);
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(utterance);
    },
    [ttsSupported]
  );

  const stopSpeaking = useCallback(() => {
    if (ttsSupported) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [ttsSupported]);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      if (ttsSupported) window.speechSynthesis.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    sttSupported,
    ttsSupported,
    listening,
    interimTranscript,
    speaking,
    autoSpeak,
    setAutoSpeak,
    voiceError,
    startListening,
    stopListening,
    speak,
    stopSpeaking,
  };
}
