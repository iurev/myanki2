import axios from 'axios';
import fs from 'fs';
import path from 'path';

async function splitChapter(chapterNumber) {
    try {
        // Step 1: Read the chapter file
        const chapterFile = `chapters/upart-002-chapter-${chapterNumber}.xhtml`;
        console.log(`Reading chapter file: ${chapterFile}`);
        
        if (!fs.existsSync(chapterFile)) {
            throw new Error(`Chapter file not found: ${chapterFile}`);
        }
        
        const chapterContent = fs.readFileSync(chapterFile, 'utf8');
        
        // Step 2: Read the split prompt
        const splitPrompt = fs.readFileSync('split.md', 'utf8');
        
        // Step 3: Send to OpenRouter API
        console.log('Sending request to OpenRouter API...');
        const response = await axios.post('https://openrouter.ai/api/v1/chat/completions', {
            model: 'google/gemini-2.5-pro',
            messages: [
                {
                    role: 'user',
                    content: `${splitPrompt}\n\n---\n\nChapter content to split:\n\n${chapterContent}`
                }
            ]
        }, {
            headers: {
                'Authorization': `Bearer ${process.env.OPENROUTER_API_KEY}`,
                'Content-Type': 'application/json'
            }
        });
        
        const aiResponse = response.data.choices[0].message.content;
        console.log('Received response from OpenRouter API');
        
        // Step 4: Split response by "@@@"
        const sections = aiResponse.split('@@@').map(section => section.trim()).filter(section => section.length > 0);
        console.log(`Found ${sections.length} sections`);
        
        // Step 5: Create chapter folder
        const chapterDir = `chapter${chapterNumber}`;
        if (!fs.existsSync(chapterDir)) {
            fs.mkdirSync(chapterDir, { recursive: true });
            console.log(`Created directory: ${chapterDir}`);
        }
        
        // Step 6: Save sections to files
        sections.forEach((section, index) => {
            const fileName = `${chapterDir}/${index + 1}.md`;
            fs.writeFileSync(fileName, section);
            console.log(`Created: ${fileName}`);
        });
        
        console.log(`Successfully split chapter ${chapterNumber} into ${sections.length} sections`);
        
    } catch (error) {
        console.error('Error:', error.message);
        if (error.response) {
            console.error('API Error:', error.response.data);
        }
    }
}

// Get chapter number from command line argument
const chapterNumber = process.argv[2];
if (!chapterNumber) {
    console.error('Usage: node chapter-splitter.js <chapter-number>');
    process.exit(1);
}

splitChapter(chapterNumber);