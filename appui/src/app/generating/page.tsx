"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import styles from "./Generating.module.css";
import { api } from "@/lib/api";

type StepStatus = "inactive" | "active" | "completed";

export default function GeneratingStatePage() {
  const router = useRouter();
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("Preparing request...");
  const [stepIndex, setStepIndex] = useState(0);
  const stepsList = [
    { label: "Parsing JD", status: "Preparing to parse job description..." },
    { label: "Matching experience", status: "Matching your experience..." },
    { label: "Rewriting bullets", status: "Rewriting resume bullets..." },
    { label: "Optimizing for ATS", status: "Optimizing for ATS..." },
  ];

  useEffect(() => {
    let mounted = true;
    let cancelled = false;
    const run = async () => {
      const raw = typeof window !== "undefined" ? localStorage.getItem("pending_generate_payload") : null;
      if (!raw) {
        setError("Nothing to generate. Please start from the input page.");
        router.replace("/resume-input");
        return;
      }
      let payload: any;
      try {
        payload = JSON.parse(raw);
      } catch (err) {
        setError("Invalid pending request. Please retry from the input page.");
        router.replace("/resume-input");
        return;
      }

      // Animate through steps
      for (let i = 0; i < stepsList.length; i++) {
        if (!mounted || cancelled) return;
        setStepIndex(i);
        setStatus(stepsList[i].status);
        setProgress(Math.round((i / stepsList.length) * 100 * 0.85));
        await new Promise((resolve) => setTimeout(resolve, 700 + Math.random() * 600));
      }

      setStatus("Calling generator...");
      setProgress(85);
      const res = await api.generate(payload);
      if (!mounted || cancelled) return;
      if (!res.ok) {
        setError(res.error);
        setStatus("Generation failed.");
        setProgress(0);
        return;
      }

      const data = res.data;
      const newId = data.resume_id || "";
      if (newId) {
        localStorage.setItem("resume_id", newId);
      }
      if (payload.jd_text) {
        localStorage.setItem("jd_text", payload.jd_text);
      }
      if (payload.company_name) {
        localStorage.setItem("company_name", payload.company_name);
      }
      if (payload.position_name) {
        localStorage.setItem("position_name", payload.position_name);
      }
      localStorage.removeItem("pending_generate_payload");

      setStatus("Finalizing preview...");
      setProgress(100);
      setTimeout(() => {
        if (!cancelled) router.replace(`/resume-editor?resumeId=${newId}`);
      }, 600);
    };

    void run();
    return () => {
      mounted = false;
      cancelled = true;
    };
  }, [router]);

  const steps = useMemo(() => {
    return stepsList.map((step, idx) => {
      let status: StepStatus = "inactive";
      if (stepIndex > idx) status = "completed";
      else if (stepIndex === idx) status = "active";
      return { label: step.label, status };
    });
  }, [stepIndex, stepsList]);

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <div className={styles.iconCircle}>
          <span style={{ fontSize: 40, color: "#7c3aed" }}>✦</span>
        </div>
        <div className={styles.title}>Generating your resume</div>
        <div className={styles.subtitle}>{status}</div>
        {error && (
          <div style={{ color: "#dc2626", fontWeight: 600, marginBottom: 12, textAlign: "center" }}>
            {error}
          </div>
        )}
        <div className={styles.steps}>
          {steps.map((step) => (
            <div
              key={step.label}
              className={
                styles.step +
                " " +
                (step.status === "completed"
                  ? styles.completed
                  : step.status === "active"
                  ? styles.active
                  : "")
              }
            >
              <span
                className={
                  styles.stepIcon +
                  " " +
                  (step.status === "completed"
                    ? styles.completed
                    : step.status === "active"
                    ? styles.active
                    : styles.inactive)
                }
              >
                {step.status === "completed" ? "✔" : step.status === "active" ? "⦿" : "✦"}
              </span>
              {step.label}
            </div>
          ))}
        </div>
        <div className={styles.progressBar}>
          <div className={styles.progress} style={{ width: `${progress}%` }} />
        </div>
        <div style={{ textAlign: "center", color: "#6b7280", fontWeight: 500, marginBottom: 16 }}>
          {progress}% complete
        </div>
        <button
          className={styles.cancelButton}
          onClick={() => {
            localStorage.removeItem("pending_generate_payload");
            router.replace("/resume-input");
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
