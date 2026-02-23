# Advanced RVC Studio Production Guide: Mastering Voice Conversion for Professional Mixing

This document serves as the definitive, studio-grade technical manual for utilizing Retrieval-based Voice Conversion (RVC) in professional audio engineering and music production. By bypassing convenience-oriented defaults and unstable experimental branches, this guide focuses entirely on maximizing acoustic fidelity, phase coherence, and musicality.

## Table of Contents
1. [Architectural Foundations: Vocoders and Sample Rates](#1-architectural-foundations-vocoders-and-sample-rates)
2. [Deep Dive: The Elite Pre-Trained Base Models](#2-deep-dive-the-elite-pre-trained-base-models)
3. [Model Selection Matrix by Vocal Archetype](#3-model-selection-matrix-by-vocal-archetype)
4. [The Blacklist: Models and Architectures to Avoid](#4-the-blacklist-models-and-architectures-to-avoid)
5. [Inference Engine Optimization](#5-inference-engine-optimization)
6. [Pro Audio Post-Processing Strategy](#6-pro-audio-post-processing-strategy)

---

## 1. Architectural Foundations: Vocoders and Sample Rates

In voice conversion, achieving studio quality requires understanding the strict separation between the **Pre-train (Base Model)**—which dictates musicality, pronunciation, and tone—and the **Vocoder**—which synthesizes the mathematical spectrogram back into an audible waveform.

*   **HiFi-GAN (Standard v2):** The robust legacy standard. Highly compatible, but introduces micro-resonances and a slight metallic "buzz" in the 3kHz–5kHz range when pushed to extreme volumes or high pitches.
*   **RefineGAN (Advanced/SSS):** The audiophile standard. Requires specialized pre-trains and a backend engine like SeoulStreamingStation (via Applio). It drastically reduces phase smearing and metallic artifacts, yielding a pristine high-end.
*   **The Sample Rate Mandate:** For professional mixing, **48kHz** or **44.1kHz** are mandatory. Standard 40kHz models place a hard brick-wall filter on the audio around 16kHz. When you apply a high-shelf EQ boost in a mix to add "air," a 40kHz model will expose an artificial, low-bitrate digital cutoff.

---

## 2. Deep Dive: The Elite Pre-Trained Base Models

The following models represent the pinnacle of current RVC training for production environments. 

### A. HiFi-GAN KLM 4.9 (48k)
*   **Background & History:** Developed by the SeoulStreamingStation (SSS) and Rejekts community. The KLM (Korean Large Model) lineage was built specifically to solve the "muffled" nature of the original Chinese RVC v2 base models. Version 4.9 (`KLM49`) represents the final stable, highly-polished release of the primary KLM architecture before experimental embedders were introduced.
*   **Training Dataset:** Massive curation of pristine, studio-isolated acapellas, heavily leaning toward Korean Pop, English Pop, and high-tier voice acting.
*   **Training Process:** Hyper-optimized for pitch accuracy and vibrato retention over thousands of epochs. Noise was strictly filtered out of the dataset.
*   **Evaluation & Consensus:** KLM49 48k is universally recognized as the gold standard for **musicality**. It possesses an inherent understanding of breath support and sustained notes.
*   **Target Usage:** Lead pop vocals, high-register singing, anime dubbing, and breathy ASMR.
*   **Repository / Link:** `HuggingFace: SeoulStreamingStation/KLM49_HFG`

### B. HiFi-GAN TITAN Medium/Large (48k)
*   **Background & History:** Developed by blaise-tk and adopted heavily by the IA Hispano community. TITAN was built under the Ov2 (Original v2) philosophy, prioritizing dataset scale and extreme speaker diversity over sterile purity.
*   **Training Dataset:** A sprawling, multi-lingual, multi-gender dataset encompassing hundreds of hours of podcasts, raw speech, interviews, and diverse singing styles. 
*   **Training Process:** Designed for "Generalization." By exposing the neural network to minor imperfections and varied room tones during pre-training, TITAN learns to reconstruct the core human voice robustly, even if the user's fine-tuning dataset is slightly flawed.
*   **Evaluation & Consensus:** TITAN is the heavyweight champion for low-end frequency stability. It prevents the "thinning" effect often caused by KLM. It is the most robust and fault-tolerant high-fidelity model available.
*   **Target Usage:** Deep baritone/bass singing, rap, rock vocals, podcasting, and general speech.
*   **Repository / Link:** `HuggingFace: blaise-tk/TITAN`

### C. RefineGAN KLM 5.0 "exp1" (44.1k)
*   **Background & History:** A legendary but volatile branch. Developers combined the pristine KLM dataset with the advanced RefineGAN vocoder at a 44.1kHz sample rate. It was later deleted from primary repos due to training instability for novice users, but remains highly prized by audio engineers.
*   **Training Dataset:** Over 300+ hours of ultra-clean singing and studio dialogue.
*   **Training Process:** Complex adversarial training specifically targeting the RefineGAN discriminator, mapping the high-fidelity pop tone to the artifact-free vocoder.
*   **Evaluation & Consensus:** It possesses the highest acoustic ceiling of any singing model. It provides the glossy tone of KLM without the HiFi-GAN phase buzz. 
*   **Target Usage:** Flawless high-frequency female belting and professional soprano tracks.
*   **Repository / Link:** Recoverable via HuggingFace commit history at `Politrees/RVC_resources` (Commit `cf70ba3`). Look for `G_KLM50_exp1_RFG_44k.pth`.

### D. RefineGAN VCTK (44.1k or 48k)
*   **Background & History:** An adaptation of a strict academic standard by developer SimplCup. It strips away the "pop" bias of KLM to provide a mathematically neutral voice conversion baseline.
*   **Training Dataset:** The CSTR VCTK Corpus. ~110 English speakers reading news passages in a semi-anechoic (dead silent) chamber. Zero singing data.
*   **Training Process:** Clinically trained to map phonemes perfectly without adding artificial resonance, vibrato, or EQ.
*   **Evaluation & Consensus:** Flawless intelligibility and zero phase distortion. However, because it lacks musical data, it relies entirely on the user's dataset to learn how to sing, which can result in "stiff" musical phrasing.
*   **Target Usage:** High-end audiobooks, clinical narration, dry podcasting, and background/choir vocal layers where transparency is needed.
*   **Repository / Link:** `HuggingFace: SimplCup/RefGanVCTK`

---

## 3. Model Selection Matrix by Vocal Archetype

To achieve realistic results, the Pre-train must align with the target's vocal physiology and the project's medium.

### A. Female Singing (Pop, Anime, Soprano/Mezzo)
*Goal: Brightness, breath support, soaring high notes, and glossy "expensive microphone" sheen.*
1.  **RefineGAN KLM5.0 (exp1) 44k:** The absolute pinnacle. Eliminates the high-frequency metallic phase buzz that ruins female belts.
2.  **HiFi-GAN KLM49 48k:** The most stable native option. Captures the "air" of a female voice beautifully, with unmatched vibrato handling.
3.  **Ov2Super 40k:** Fallback option. Best used only if the target dataset is critically small (under 3 minutes of audio).

### B. Deep Male Singing (Baritone, Bass, Rock, Warmth)
*Goal: Chest resonance, thickness, stability in the low-mids (100Hz - 300Hz), and grit.*
1.  **HiFi-GAN TITAN 48k:** The undisputed choice. It gives a baritone voice a thick, natural chest resonance that KLM inherently thins out.
2.  **HiFi-GAN KLM49 48k:** Secondary option for softer, breathier male ballads, though it may artificially brighten the tone.
3.  **RefineGAN VCTK 44k/48k:** Ensures low frequencies stay incredibly tight and punchy without getting muddy, though it lacks inherent warmth.

### C. High Male Singing (Tenor, R&B, K-Pop)
*Goal: Smooth transitions between chest and head voice, clean falsetto, dynamic range.*
1.  **HiFi-GAN KLM49 48k:** Tenor vocals thrive on this model due to the K-Pop dataset bias. It handles falsetto transitions flawlessly.
2.  **RefineGAN KLM5.0 (exp1) 44k:** Flawless phase coherence when hitting extreme tenor notes, avoiding high-mid harshness.
3.  **HiFi-GAN TITAN 48k:** Use only if the tenor sounds too "whiny" or thin on KLM; TITAN will anchor the voice with more body.

### D. Spoken Word, Podcasting, and Narration
*Goal: Intelligibility, zero musical "sing-song" artifacts, neutral tone, natural pauses.*
1.  **RefineGAN VCTK 44k/48k:** Clinically dry. Sounds like a perfect audiobook recording in an anechoic chamber.
2.  **HiFi-GAN TITAN 48k:** Excellent for creating deep, rich, stable "Radio Announcer" voices.
3.  **HiFi-GAN KLM49 48k:** Reserve only for high-energy Anime Dubbing or extreme emotional voice acting; otherwise, it is too "musical" for standard speech.

---

## 4. The Blacklist: Models and Architectures to Avoid

In the pursuit of studio quality, certain cutting-edge updates and legacy defaults must be strictly avoided.

*   **KLM9 48k (Spin V2 Embedder):** Released as a test in late 2025/early 2026. While the 48k resolution is high, the "Spin V2" feature extractor algorithm is fundamentally bugged regarding English and Korean phonetics. It crushes pronunciation, causing the AI to slur consonants and mumble. **Avoid.**
*   **"Mini" Base Models (e.g., KLM5.0 Mini):** These are lightweight developer testing models trained on ~20 hours of data (compared to 300+). They lack the neural vocabulary to understand complex pitch changes and will glitch out on dynamic singing runs.
*   **Standard RVC v2 40k Defaults:** The default Chinese pre-trains lack high-end extension and were trained with mild background noise, which they will bake into your output. 
*   **RMVPE Pitch Extraction (For Singing):** While excellent for speech, RMVPE induces micro-jitter on sustained musical notes. It must be avoided for singing models.

---

## 5. Inference Engine Optimization

When generating the final audio from your trained model, use these exact parameters to ensure studio fidelity:

*   **F0 Extraction Method:** **FCPE** (Fast Context-aware Pitch Estimator). This is vastly superior for singing, holding long notes completely steady without the jitter of RMVPE.
*   **Hop Length:** Set to **64** (or **32** if your hardware and interface allow). Lower hop lengths drastically increase acoustic fidelity and high-frequency resolution at the cost of rendering time.
*   **Protect Voiceless (Consonant Protection):** Set to **0.33**. The default of 0.5 protects too much (causing pitch tracking failures), while 0 turns "S" and "T" sounds into robotic electronic noises. 0.33 perfectly preserves natural diction.

---

## 6. Pro Audio Post-Processing Strategy

No AI output is mix-ready out of the box. The neural synthesis process fundamentally alters phase and transient data. To bridge the uncanny valley and place an RVC track into a professional mix, apply the following DAW signal chain.

### A. The "AI Whistle" (Resonance Suppression)
RVC models (especially HiFi-GAN) accumulate harsh, synthetic resonances between **2.5kHz and 5kHz**.
*   **Solution:** Do not use a static EQ, which will kill the vocal's presence. Use a dynamic resonance suppressor like **Oeksound Soothe2** (set to "Hard" mode, focusing entirely on the upper mids) or **Baby Audio Smooth Operator**. Alternatively, use a tightly-notched multi-band compressor to duck 3.5kHz only when the vocal gets loud.

### B. Robotic Sibilance (Double De-Essing)
The AI frequently misinterprets "S", "T", and "Ch" phonemes, synthesizing them as piercing bursts of white noise rather than human breath.
*   **Solution:** AI vocals require a two-stage de-essing process.
    1.  *Stage 1:* Target the lower sibilance (4kHz - 6kHz) early in the chain to catch harsh "Ch" and "Sh" impacts.
    2.  *Stage 2:* Place a second De-Esser at the end of the vocal chain, targeting extreme highs (8kHz - 11kHz) to catch the piercing "S" hiss.

### C. Transient Smearing (Consonant Restoration)
The vocoder smoothing process blunts the hard impacts of plosives ("P," "B," "K"), resulting in a vocal that lacks energy or sounds like the singer has a slight lisp.
*   **Solution:** Insert a **Transient Shaper** (e.g., NI Transient Master or Kilohearts Transient). Increase the "Attack" parameter by +2 to +4 dB. This forces the consonants to punch through the mix, restoring human intent and rhythm to the phrasing.

### D. The "Brickwall Muffle" (High-End Harmonic Generation)
Even on 48kHz models, RVC struggles to accurately generate the intricate harmonics above 14kHz. Standard EQ boosts will only amplify noise because the harmonic data is missing.
*   **Solution 1 (Excitation):** Generate new harmonics using a saturation/exciter plugin. **Slate Digital Fresh Air**, **Aphex Vintage Aural Exciter**, or **FabFilter Saturn 2** applied lightly to the top end will synthesize the missing "air."
*   **Solution 2 (The Hybrid Trick):** Take the extreme high-end (10kHz+) of the *original* human guide vocal, apply a steep high-pass filter, and layer it underneath the AI vocal. The AI provides the tone; the human provides the authentic breath and air.

### E. Stereo Phase Collapse (Centering)
RVC synthesis can occasionally output audio that is micro-seconds out of phase between the Left and Right channels, causing the lead vocal to sound "wide" or "swimming."
*   **Solution:** Lead vocals must be anchored. Sum the raw AI vocal to **True Mono** using a utility plugin in your DAW before applying any stereo effects, delays, or reverbs.
