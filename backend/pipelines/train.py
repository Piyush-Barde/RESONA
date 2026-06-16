# backend/pipelines/train.py
# CODE ARCHITECTURE OPTIMIZED FOR FREE GOOGLE COLAB TESLA T4 GPU RUNTIMES
# RUN THIS BOX INSIDE COLAB AFTER INSTALLING DEPENDENCIES:
# !pip install -q bitsandbytes transformers PEFT trl datasets accelerate

import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

def format_prompts(batch):
    """
    Reformats raw human text data into the exact ChatML structure 
    Resona needs for low-latency streaming inference.
    """
    system_prompt = "You are Resona, an empathetic, highly supportive, and concise voice assistant. Actively validate feelings, keep responses short, and prioritize conversational comfort."
    
    formatted_texts = []
    # EmpatheticDialogues uses 'prompt' for the user situation and 'utterance' for the response
    for user_text, assistant_text in zip(batch['prompt'], batch['utterance']):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text}
        ]
        formatted_texts.append(messages)
        
    return {"text": formatted_texts}

def run_fine_tuning_pipeline():
    print("🚀 Initializing Resona Cognitive Fine-Tuning Core Pipeline...")
    
    # 1. Target a hyper-fast, highly modern open-source base model
    model_id = "Qwen/Qwen2.5-1.5B-Instruct"
    
    # 2. Setup 4-Bit BitsAndBytes Quantization Config to protect free GPU VRAM limits
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16
    )
    
    print(f"📥 Loading Base Foundation Model: {model_id}")
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config,
        device_map="auto"
    )
    
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.pad_token = tokenizer.eos_token
    
    # Prepare model weights for memory-efficient gradient updates
    model = prepare_model_for_kbit_training(model)
    
    # 3. Configure Parameter-Efficient LoRA Adapters
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, lora_config)
    
    print("📊 Stream-downloading authentic human empathetic dialogue dataset from Hugging Face...")
    raw_dataset = load_dataset("facebook/empathetic_dialogues", split="train")
    
    # Select a clean subset (e.g., 2000 samples) to ensure super fast training on Colab's free GPU
    dataset_subset = raw_dataset.select(range(2000))
    dataset = dataset_subset.map(format_prompts, batched=True)
    print(f"✨ Successfully ingested and tokenized {len(dataset)} real-world human interactions.")
    
    # 4. Set Professional Supervised Fine-Tuning (SFT) Hyperparameters
    training_args = TrainingArguments(
        output_dir="./resona_weights_output",
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=60, 
        learning_rate=2e-4,
        fp16=True,
        logging_steps=10,
        optim="paged_adamw_8bit"
    )
    
    # 5. Initialize the Trainer Interface
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=lora_config,
        max_seq_length=512,
        tokenizer=tokenizer,
        args=training_args,
    )
    
    print("🔥 Commencing Gradient Backpropagation Training Loop...")
    trainer.train()
    
    print("📦 Merging and Exporting Fine-Tuned Custom Resona Adapter Weights...")
    trainer.model.save_pretrained("./resona-custom-adapters")
    print("✨ Milestone Accomplished. Neural weights successfully trained!")

if __name__ == "__main__":
    run_fine_tuning_pipeline()