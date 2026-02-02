import styles from './Landing.module.css';

export default function LandingPage() {
  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.logo}>
          <span style={{fontSize: 28, color: '#4F46E5'}}>✦</span>
          <span>ResumeAI</span>
        </div>
        <nav className={styles.nav}>
          <a href="#how">How it works</a>
          <a href="#examples">Examples</a>
        </nav>
        <div className={styles.cta}>
          <a href="/resume-input">
            <button className={styles.buttonPrimary}>Create Resume</button>
          </a>
        </div>
      </header>
      <main className={styles.main}>
        <section>
          <h1 className={styles.heroTitle}>Generate a job-ready resume in minutes</h1>
          <p className={styles.heroDesc}>
            Our AI-powered platform analyzes job descriptions and crafts tailored resumes that get past ATS systems and impress hiring managers.
          </p>
          <div className={styles.buttonRow}>
            <a href="/resume-input">
              <button className={styles.buttonPrimary}>Create Resume</button>
            </a>
            <a href="/resume-input">
              <button className={styles.buttonSecondary}>Upload Existing Resume</button>
            </a>
          </div>
        </section>
      </main>
    </div>
  );
}
