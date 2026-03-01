# Advanced RVC Studio Production Guide: Mastering Voice Conversion for Professional Mixing

This document serves as the definitive, studio-grade technical manual for utilizing Retrieval-based Voice Conversion (RVC) in professional audio engineering and music production. By bypassing convenience-oriented defaults and unstable experimental branches, this guide focuses entirely on maximizing acoustic fidelity, phase coherence, and musicality.

## Table of Contents
1. [Quick Reference Cheat Sheets](#1-quick-reference-cheat-sheets)
2. [Architectural Foundations: Vocoders and Sample Rates](#2-architectural-foundations-vocoders-and-sample-rates)
3. [Deep Dive: The Elite Pre-Trained Base Models](#3-deep-dive-the-elite-pre-trained-base-models)
4. [Language and Organization Matching Matrix](#4-language-and-organization-matching-matrix)
5. [Model Selection Matrix by Vocal Archetype](#5-model-selection-matrix-by-vocal-archetype)
6. [The Blacklist: Models and Architectures to Avoid](#6-the-blacklist-models-and-architectures-to-avoid)
7. [Applio Training Configuration for Maximum Fidelity](#7-applio-training-configuration-for-maximum-fidelity)
8. [Applio Inference Configuration (Generating the Voice)](#8-applio-inference-configuration-generating-the-voice)
9. [Pro Audio Post-Processing Strategy](#9-pro-audio-post-processing-strategy)

---

## 1. Quick Reference Cheat Sheets

For immediate studio application, utilize the following summary tables. Detailed explanations of the mathematics and reasoning behind these settings are found in the subsequent chapters.

### Table 1: Best Models by Purpose & Language
| Target Archetype / Purpose | Best Languages | Primary Studio Model | Secondary Fallback |
| :--- | :--- | :--- | :--- |
| **Female Pop / High Vocals** | EN, KO, JA, ZH | RefineGAN KLM 5.0 (44.1k) | HiFi-GAN KLM 4.9 (48k) |
| **Deep Male / Baritone / Rock** | EN, ES, FR, DE, RU | HiFi-GAN TITAN Med (48k) | RefineGAN VCTK (44.1k) |
| **High Male / Tenor / R&B** | EN, KO, JA, ZH | HiFi-GAN KLM 4.9 (48k) | RefineGAN KLM 5.0 (44.1k) |
| **Spoken Word / Audiobook** | EN, ES, DE, IT | RefineGAN VCTK (44.1k) | HiFi-GAN TITAN Med (48k) |

### Table 2: Applio Training Settings (Studio Standard)
| Parameter | Studio Recommendation | Rationale |
| :--- | :--- | :--- |
| **Sample Rate** | 48000Hz or 44100Hz | Prevents high-frequency "brickwall" cutoffs at 16kHz. |
| **Embedder Model** | `contentvec_base_v2` | Best speaker disentanglement; prevents source vocal bleed. |
| **Batch Size** | 8 | Introduces necessary gradient noise to capture human texture. |
| **Total Epochs** | 150 to 300 (Scales to data) | Shorter dataset = more epochs. Longer dataset = fewer epochs. |
| **Index Algorithm** | `faiss` (or `KMeans`) | Creates a high-res dictionary; avoids "Auto" blurring. |
| **Overtraining Detector** | OFF / Disabled | GAN loss curves are deceptive. Only rely on ear A/B testing. |

### Table 3: Applio Inference Settings (Voice Conversion)
| Parameter | Studio Recommendation | Rationale |
| :--- | :--- | :--- |
| **F0 Pitch Algorithm** | `RMVPE` (or `Mangio-Crepe`) | RMVPE for stability. Crepe (Hop 64) for micro-details on dry audio. |
| **Feature Retrieval (Index)** | 0.60 to 0.75 | Balances clone accuracy (high) with artifact reduction (low). |
| **Protect Voiceless** | 0.33 | Preserves consonants. 0.5 flatlines pitch; 0 creates robotic "S" sounds. |
| **RMS Mix Rate** | 0.80 to 1.00 | Retains the volume dynamics of your human guide vocal for DAW mixing. |

### Table 4: Studio Post-Processing (Fixing AI Audio)
| Audio Problem | The Solution | Studio Tool / Technique |
| :--- | :--- | :--- |
| **"AI Whistle" (3k-5k buzz)** | Dynamic Resonance Suppression | TDR Nova, Soothe2, or Trackspacer feedback trick. |
| **Transient Smearing / Lisp** | Attack Enhancement | Kilohearts Transient Shaper, Flux:: BitterSweet. |
| **Robotic Sibilance ("S")** | Double De-Essing | De-ess at 4k-6k (Ch/Sh), then De-ess again at 8k-11k (S). |
| **Missing Air / Muffled Highs** | Harmonic Excitation | Slate Fresh Air, Aphex Exciter, or High-pass human guide. |
| **Stereo Phase "Swimming"** | Phase Centering | Sum the raw AI lead vocal to True Mono in the DAW. |

---

## 2. Architectural Foundations: Vocoders and Sample Rates

In voice conversion, achieving studio quality requires understanding the strict separation between the **Pre-train (Base Model)**—which dictates musicality, pronunciation, and tone—and the **Vocoder**—which synthesizes the mathematical spectrogram back into an audible waveform.

*   **HiFi-GAN (Standard v2):** The robust legacy standard. Highly compatible, but introduces micro-resonances and a slight metallic "buzz" in the 3kHz–5kHz range when pushed to extreme volumes or high pitches.
*   **RefineGAN (Advanced/SSS):** The audiophile standard. Requires specialized pre-trains and a backend engine like SeoulStreamingStation (via Applio). It drastically reduces phase smearing and metallic artifacts, yielding a pristine high-end.
*   **The Sample Rate Mandate:** For professional mixing, **48kHz** or **44.1kHz** are mandatory. Standard 40kHz models place a hard brick-wall filter on the audio around 16kHz. When you apply a high-shelf EQ boost in a mix to add "air," a 40kHz model will expose an artificial, low-bitrate digital cutoff.

---

## 3. Deep Dive: The Elite Pre-Trained Base Models

The following models represent the pinnacle of current RVC training for production environments.

### A. HiFi-GAN KLM 4.9 (48k)
*   **Background & Organizations:** Developed by the **SeoulStreamingStation (SSS)** and the **Rejekts** community. The KLM (Korean Large Model) lineage was built specifically to solve the "muffled" nature of the original Chinese RVC v2 base models. 
*   **Training Dataset:** Massive curation of pristine, studio-isolated acapellas, heavily leaning toward Korean Pop, English Pop, and high-tier voice acting. Noise was strictly filtered out.
*   **Evaluation & Consensus:** KLM 4.9 48k is universally recognized as the gold standard for **musicality**. It possesses an inherent understanding of breath support, sustained notes, and vibrato.
*   **Repository / Link:** `HuggingFace: SeoulStreamingStation/KLM49_HFG`

### B. HiFi-GAN TITAN Medium (48k)
*   **Background & Organizations:** Developed by developer **blaise-tk** and adopted heavily by the **IA Hispano** community (the hub responsible for Applio). 
*   **"Large" vs. "Medium":** While experimental "Large" branches existed, **TITAN Medium** is the official, stable flagship release. The "Medium" designation refers to the optimal parameter weight blaise-tk finalized to balance generalization without overfitting. 
*   **Training Dataset:** A sprawling, multi-lingual dataset encompassing hundreds of hours of podcasts, raw speech, interviews, and diverse singing styles. 
*   **Evaluation & Consensus:** TITAN Medium is the heavyweight champion for low-end frequency stability. It prevents the "thinning" effect often caused by KLM. It is the most robust and fault-tolerant high-fidelity model available.
*   **Repository / Link:** `HuggingFace: blaise-tk/TITAN`

### C. RefineGAN KLM 5.0 "exp1" (44.1k)
*   **Background & History:** A legendary but volatile branch from the SSS/Rejekts team. Developers combined the pristine KLM dataset with the advanced RefineGAN vocoder at a 44.1kHz sample rate. It was later removed from primary repos due to training instability for novice users, but remains highly prized by audio engineers.
*   **Evaluation & Consensus:** It possesses the highest acoustic ceiling of any singing model. It provides the glossy tone of KLM without the HiFi-GAN phase buzz. 
*   **Repository / Link:** Recoverable via HuggingFace commit history at `Politrees/RVC_resources` (Commit `cf70ba3`). Look for `G_KLM50_exp1_RFG_44k.pth`.

### D. RefineGAN VCTK (44.1k)
*   **Background & History:** An adaptation of a strict academic standard by developer **SimplCup**. True, stable RefineGAN VCTK bases are strictly **44.1k** (and 40k). 
*   **Training Dataset:** The CSTR VCTK Corpus. ~110 English speakers reading news passages in a semi-anechoic (dead silent) chamber. Zero singing data.
*   **Evaluation & Consensus:** Flawless intelligibility and zero phase distortion. However, because it lacks musical data, it relies entirely on the user's fine-tuning dataset to learn how to sing, which can result in "stiff" musical phrasing.
*   **Repository / Link:** `HuggingFace: SimplCup/RefGanVCTK`

---

## 4. Language and Organization Matching Matrix

Pre-trained base models inherently learn the phonetic structures, formants, and rhythmic cadences of their training data. Matching the base model to the target language yields significantly higher pronunciation accuracy.

*   **Korean, Japanese, Chinese (Asian Languages):**
    *   **Winner:** **KLM 4.9**. Developed by SeoulStreamingStation, the dataset is incredibly rich in Asian phonetics. It effortlessly handles the tonal nuances of Mandarin and the staccato syllables of Japanese without applying a Western "accent."
*   **Spanish, French, Italian, Portuguese (Romance Languages):**
    *   **Winner:** **TITAN Medium**. Adopted by IA Hispano, TITAN was trained on a massively diverse dataset that includes vast amounts of Spanish and European speech. It forms the rolling "R"s and soft vowels of Romance languages flawlessly.
*   **German, Russian, Dutch (Germanic / Slavic):**
    *   **Winner:** **TITAN Medium**. These languages require strong, guttural consonant reproduction. TITAN's robust handling of low-mid frequencies and plosives prevents these languages from sounding "smoothed out" or lisped.
*   **English:**
    *   **Pop Singing:** **KLM 4.9** (Produces a highly-produced, American/K-Pop English style).
    *   **Speech/Rap/Indie:** **TITAN Medium** or **VCTK** (Produces a wider variety of natural English accents without artificial pop gloss).

---

## 5. Model Selection Matrix by Vocal Archetype

To achieve realistic results, the Pre-train must align with the target's vocal physiology and the project's medium.

### A. Female Singing (Pop, Anime, Soprano/Mezzo)
1.  **RefineGAN KLM5.0 (exp1) 44.1k:** The absolute pinnacle. Eliminates the high-frequency metallic phase buzz that ruins female belts.
2.  **HiFi-GAN KLM49 48k:** The most stable native option. Captures the "air" of a female voice beautifully, with unmatched vibrato handling.

### B. Deep Male Singing (Baritone, Bass, Rock, Warmth)
1.  **HiFi-GAN TITAN Medium 48k:** The undisputed choice. It gives a baritone voice a thick, natural chest resonance that KLM inherently thins out.
2.  **RefineGAN VCTK 44.1k:** Ensures low frequencies stay incredibly tight and punchy without getting muddy, though it lacks inherent warmth.

### C. High Male Singing (Tenor, R&B, K-Pop)
1.  **HiFi-GAN KLM49 48k:** Tenor vocals thrive on this model due to the dataset bias. It handles falsetto transitions flawlessly.
2.  **HiFi-GAN TITAN Medium 48k:** Use only if the tenor sounds too "whiny" or thin on KLM; TITAN will anchor the voice with more body.

### D. Spoken Word, Podcasting, and Narration
1.  **RefineGAN VCTK 44.1k:** Clinically dry. Sounds like a perfect audiobook recording in an anechoic chamber.
2.  **HiFi-GAN TITAN Medium 48k:** Excellent for creating deep, rich, stable "Radio Announcer" voices.

---

## 6. The Blacklist: Models and Architectures to Avoid

In the pursuit of studio quality, certain cutting-edge updates and legacy defaults must be strictly avoided.

*   **KLM9 48k (Spin V2 Embedder):** While the 48k resolution is high, the "Spin V2" feature extractor algorithm is fundamentally bugged regarding English and Korean phonetics. It crushes pronunciation, causing the AI to slur consonants and mumble. 
*   **"Mini" Base Models (e.g., KLM5.0 Mini):** These are lightweight developer testing models trained on minimal data. They lack the neural vocabulary to understand complex pitch changes and will glitch out on dynamic singing runs.
*   **Standard RVC v2 40k Defaults:** The default Chinese pre-trains lack high-end extension and were trained with mild background noise, which they will bake into your output. 
*   **FCPE Pitch Extraction (For Singing):** Prone to dropping pitches and hallucinating notes on complex melodies. Too unstable for professional reliance.

---

## 7. Applio Training Configuration for Maximum Fidelity

When your goal is professional studio-grade audio, convenience-based training metrics must be abandoned. How the neural network learns is just as important as the pre-trained base model. 

### A. Total Epochs (The Scaling Rule)
An "Epoch" is one complete pass through your dataset. The correct number of Epochs to train depends entirely on the length of your clean dataset.
*   **10 to 15 Minutes of Data (Standard):** Train for **250 to 300 Epochs**.
*   **30+ Minutes of Data (Large):** Train for **100 to 150 Epochs**.
*   **1 to 3 Minutes of Data (Tiny):** Train for **400 to 500 Epochs**.
*   *The Studio Rule:* Save your model every 25 to 50 Epochs. The model will eventually "overfit" (memorize background noise and become robotic). You must A/B test the last few saved `.pth` files to find the exact peak before degradation occurred.

### B. Batch Size: 8 vs. 4
Batch size dictates how many audio chunks the neural network analyzes simultaneously before updating its weights.
*   **The Recommendation:** **`8`** is the studio sweet spot.
*   **Why Batch Size 4 is worse for standard datasets:** While some theorize that dropping the batch size to 4 forces the model to learn more "micro-details," it actually introduces excessive *gradient noise*. The model's weights bounce around too violently during training, which can result in a "scratchy" or unstable vocal tone. 
*   *Exception:* Only drop to a batch size of 4 if your dataset is critically small (under 2 minutes) or if your GPU VRAM is severely limited.

### C. The Embedder Model (Feature Extractor)
*   **The Recommendation:** **`contentvec_base_v2`** (or `contentvec`).
*   **The Science:** `contentvec` was specifically engineered by Microsoft for *speaker disentanglement*. It is mathematically skilled at separating *what* is being said from *who* is saying it. Standard `hubert_base` often accidentally bakes the original source singer's vocal weight into the final output. `contentvec` ensures your AI voice sounds exactly like your target dataset.

### D. The Index Algorithm
After the model finishes training, Applio generates an `.index` file—a massive dictionary of your dataset's vocal tones. Applio usually offers three choices: `Auto`, `Faiss`, or `KMeans`.
*   **The Recommendation:** **`faiss`**.
*   **Why it wins:** Selecting `faiss` forces the builder to utilize Facebook's AI Similarity Search directly (typically creating a high-resolution FlatL2 index). This results in a larger file size, but it retains the highest 1:1 fidelity of your dataset's micro-expressions.
*   **Why to avoid `kmeans`:** KMeans aggressively clusters the data points, grouping similar sounds together and averaging them out to save RAM. It creates a tiny file but blurs the intricate details of the voice. `Auto` usually defaults to a fast KMeans approach and should be avoided.

### E. Overtraining Detector (Why Early Stopping Ruins Models)
*   **The Recommendation:** **Turn it OFF / Disable it.** (If the UI has an "early stopping" or "overtraining" toggle, disable it. If it uses a numerical threshold, set it to an impossible number like 1000).
*   **The Proof & Architectural Reasoning:** 
    Applio's automated stopping features monitor mathematical "loss." In a standard machine learning model, a rising loss curve means the model is degrading. However, RVC utilizes **VITS**, built on a **GAN (Generative Adversarial Network)** architecture. 
    A GAN consists of two neural networks fighting each other (Generator vs. Discriminator). Because they are competing, the loss graphs are highly deceptive. If the Generator's numerical loss spikes upward, it frequently means the Generator is attempting to learn complex, chaotic human textures (such as vocal fry, breathiness, or rasp), temporarily increasing mathematical error before resolving into high-fidelity audio. 
    If you leave early stopping enabled, the software will halt training during one of these mathematical spikes, resulting in a model that is "safe" mathematically but perceptually flat and sterile. Algorithms cannot hear musicality. Rely only on generating epochs and conducting human A/B listening tests.

---

## 8. Applio Inference Configuration (Generating the Voice)

A perfectly trained model can still output terrible audio if the inference (conversion) settings are misconfigured. To extract the highest studio fidelity during voice generation, apply these strict parameters.

### A. F0 Pitch Extraction Algorithm
You do *not* have to use the same pitch extraction engine for training and inference.
*   **RMVPE (Robust Minute Voice Pitch Estimator):** *The Studio Standard.* RMVPE is the undisputed champion for stability. It excels at ignoring background noise in the source audio and locks onto the fundamental frequency with minimal jitter. Safest choice for 95% of studio scenarios.
*   **Mangio-Crepe:** *The High-Fidelity Alternative.* A customized fork of Crepe. It allows you to adjust the **Hop Length** (dropping it to 64 or 32). Lower hop lengths yield vastly superior micro-pitch accuracy, capturing tiny human vocal inflections perfectly. **Warning:** Crepe is highly noise-sensitive. If your guide vocal has headphone bleed, Crepe will pitch-track the noise, resulting in screeching artifacts. Use only on perfectly isolated, dry vocals.

### B. Feature Retrieval (Index Rate)
The Index Rate controls how heavily the AI relies on the `.index` dictionary file you generated during training to dictate the "accent" and "texture" of the voice.
*   **The Sweet Spot:** **0.60 to 0.75**.
*   **Why 1.0 is bad:** Setting it to maximum forces the AI to strictly copy the index file, which often introduces mechanical artifacts, stuttering, and loss of emotional dynamic range.
*   **Why 0.0 is bad:** Setting it to zero ignores your dataset's unique texture, making the output sound generic, hollow, or heavily biased toward the pre-trained base model.

### C. Protect Voiceless Consonants
This parameter dictates how the AI handles unpitched sounds like breaths, "S", "T", and "K".
*   **The Magic Number:** **0.33**.
*   **The Rationale:** If set to 0.5 (the default), the AI over-protects the audio, causing the pitch algorithm to "flatline" during breaths or fast consonants. If set to 0, the AI tries to aggressively pitch-shift unpitched sounds, resulting in robotic, screeching "S" sounds. 0.33 perfectly preserves natural human diction.

### D. RMS Mix Rate (Volume Dynamics)
This setting controls the volume envelope of the output audio.
*   **The Studio Setting:** **0.80 to 1.00**.
*   **The Rationale:** By default, Applio often sets this low (0.25), allowing the AI to invent its own volume dynamics. In a professional mix, you want the volume dynamics to perfectly mirror the human guide vocal so your DAW compressors and automation work predictably. Setting it to 1.0 forces the AI to strictly obey the volume envelope of the input file.

### E. Pitch / Key Shifting (Transpose)
*   **Same Gender / Same Register:** Leave at 0.
*   **Octave Shifts:** If a male guide is singing for a female AI model, shift by exactly **+12**. If a female guide is singing for a male AI model, shift by exactly **-12**.
*   **Warning:** Avoid shifting by odd intervals (like +4 or -7) unless you are intentionally changing the key of the song. Non-octave shifts force the AI to synthesize formants in unnatural frequency bands, leading to a "chipmunk" or "ogre" effect.

---

## 9. Pro Audio Post-Processing Strategy

No AI output is mix-ready out of the box. The neural synthesis process fundamentally alters phase and transient data. To bridge the uncanny valley, apply the following DAW signal chain.

### A. Getting Rid of the "AI Whistle" (Resonance Suppression)
RVC models accumulate harsh, synthetic resonances tightly grouped between **2.5kHz and 5kHz**. Static EQ will kill the vocal's presence; dynamic suppression is mandatory.

*   **Method 1: Dynamic EQ (TDR Nova - Free)**
    *   Insert TDR Nova. Select Band 3 and set the frequency to **3.5kHz**.
    *   Set the **Q** to roughly **2.0** (medium-wide).
    *   Activate the **Threshold** and set the Ratio to **3:1**.
    *   Pull the threshold down until the EQ only dips when the singer hits loud, screechy notes.
*   **Method 2: Multi-band Compressor (Built-in DAW)**
    *   Isolate a band strictly between 2.5kHz and 5kHz. 
    *   Set a **Fast Attack (1ms - 3ms)** to catch the synthetic chirp instantly, and a **Medium Release (50ms - 100ms)**. 
    *   Set Ratio to **4:1**. Adjust threshold to compress only the harshest peaks by -3dB to -5dB.
*   **Method 3: The TrackSpacer Feedback Trick (Advanced)**
    *   Duplicate your AI vocal track. On the *duplicate*, apply an extreme EQ: **High-pass at 2.5kHz, Low-pass at 5kHz**. Mute the output of this duplicate, but route it to a bus.
    *   Put Wavesfactory Trackspacer on your *Main* AI Vocal. Set its sidechain input to the bus you just created. 
    *   Trackspacer is now "listening" only to the harshest frequencies of the vocal, and inversely ducking those exact frequencies on the main track in real-time, perfectly smoothing the AI whistle.

### B. Transient Smearing (Restoring the Consonants)
The vocoder smoothing process blunts the hard impacts of plosives ("P," "B," "K"), resulting in a vocal that lacks energy or sounds like the singer has a lisp.

*   **Method 1: Free Plugins**
    *   **Flux:: BitterSweet:** A legendary free, one-knob transient designer. Turn the knob towards "Bitter" to instantly sharpen the consonants.
    *   **Kilohearts Transient Shaper:** (Free in their Essentials bundle). Increase the "Attack" parameter by +2 to +4 dB.
*   **Method 2: Logic Pro X (Enveloper)**
    *   Insert the built-in **Enveloper** plugin.
    *   Increase the **Gain** on the **Attack** side by roughly +15% to +20%. Leave the Release side completely neutral. 
*   **Method 3: Pro Tools / Standard Compression**
    *   If you lack a transient shaper, use a standard compressor with a very **Slow Attack (30ms+)** and a **Fast Release**. This allows the plosive consonant to pass through uncompressed, while instantly compressing the tail of the word, effectively making the consonant punchier by comparison.

### C. Robotic Sibilance (Double De-Essing)
The AI frequently misinterprets "S", "T", and "Ch" phonemes, synthesizing them as piercing bursts of white noise.
*   **Stage 1:** Target the lower sibilance (4kHz - 6kHz) early in the chain with a standard De-Esser to catch harsh "Ch" and "Sh" impacts.
*   **Stage 2:** Place a second De-Esser at the end of the vocal chain, targeting extreme highs (8kHz - 11kHz) to catch the piercing "S" hiss.

### D. The "Brickwall Muffle" (High-End Harmonic Generation)
Even on 48kHz models, RVC struggles to accurately generate the intricate harmonics above 14kHz. 
*   **Solution:** Generate new harmonics using a saturation/exciter plugin. **Slate Digital Fresh Air** (Free - push the "High Air" knob slightly) or **Aphex Vintage Aural Exciter**.
*   **The Hybrid Trick:** Take the extreme high-end (10kHz+) of the *original* human guide vocal, apply a steep high-pass filter, and layer it underneath the AI vocal. The AI provides the tone; the human guide provides the authentic breath and air.

### E. Stereo Phase Collapse (Centering)
RVC synthesis can occasionally output audio that is micro-seconds out of phase between the Left and Right channels, causing the lead vocal to sound "wide" or "swimming." Lead vocals must be anchored. Sum the raw AI vocal to **True Mono** using a utility plugin in your DAW before applying any stereo effects, delays, or reverbs.