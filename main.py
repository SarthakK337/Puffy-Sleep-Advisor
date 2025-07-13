import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import re
import time
import json

# Configure Gemini API
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-2.0-flash')

# Enhanced scraping function to capture product URLs
def scrape_puffy_site(urls):
    """Scrape Puffy website with content cleaning and URL mapping"""
    headers = {'User-Agent': 'PuffyBot/1.0 (+https://puffy.com)'}
    scraped_data = []
    
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'header', 'footer', 'nav', 'form', 'button']):
                element.decompose()
            
            # Extract and clean text
            text = soup.get_text(separator=' ', strip=True)
            text = re.sub(r'\s+', ' ', text)  # Collapse whitespaces
            
            # Capture product links
            product_links = []
            if 'products' in url or 'collections' in url:
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    if href.startswith('/products/'):
                        full_url = f"https://puffy.com{href}"
                        link_text = a_tag.get_text(strip=True)
                        if link_text and full_url not in [link['url'] for link in product_links]:
                            product_links.append({
                                "name": link_text,
                                "url": full_url
                            })
            
            scraped_data.append({
                "url": url,
                "content": text[:57000],  # Limit to 20k chars per page
                "product_links": product_links
            })
            
        except Exception as e:
            st.toast(f"⚠️ Couldn't scrape {url}: {str(e)}", icon="⚠️")
    
    return scraped_data

# List of Puffy URLs to scrape
PUFFY_URLS = [
    'https://puffy.com/',
    'https://puffy.com/pages/puffy-mattress-and-puffy-lux',
    'https://puffy.com/collections/smart-bed-sets',
    'https://puffy.com/collections/bed-frames',
    'https://puffy.com/pages/puffy-mattress-reviews',
    'https://puffy.com/pages/contact-puffy-mattress',
]

# Function to format context for Gemini
def format_context(scraped_data):
    """Format scraped data for Gemini context"""
    context_str = ""
    for data in scraped_data:
        context_str += f"### Content from {data['url']}:\n{data['content']}\n\n"
        if data['product_links']:
            context_str += "Available products:\n"
            for product in data['product_links']:
                context_str += f"- {product['name']} ({product['url']})\n"
            context_str += "\n"
    return context_str

# Streamlit app setup
st.set_page_config(page_title="Puffy Sleep Expert", page_icon="🛌")
st.title("🛌 Puffy Sleep Advisor")
st.caption("Ask me anything about mattresses, policies, or sleep technology")

# Initialize session states
if 'puffy_data' not in st.session_state:
    with st.status("Building Puffy knowledge base...", expanded=True) as status:
        st.write("📥 Collecting product information...")
        st.session_state.puffy_data = scrape_puffy_site(PUFFY_URLS)
        st.session_state.puffy_context = format_context(st.session_state.puffy_data)
        status.update(label=f"✅ Knowledge base ready! ({len(st.session_state.puffy_context)//1000}K chars)", state="complete")

# Extract all product links for recommendations
if 'all_products' not in st.session_state:
    all_products = []
    for data in st.session_state.puffy_data:
        all_products.extend(data['product_links'])
    st.session_state.all_products = all_products

# Initialize conversation history
if 'conversation' not in st.session_state:
    st.session_state.conversation = []

# Display conversation history
for message in st.session_state.conversation:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant" and "recommended_products" in message:
            st.markdown(message["content"])
            for product in message["recommended_products"]:
                st.markdown(f"- [{product['name']}]({product['url']})")
        else:
            st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask about Puffy mattresses..."):
    # Add user message to conversation
    st.session_state.conversation.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
    
    with st.chat_message("assistant", avatar="✨"):
        message_placeholder = st.empty()
        full_response = ""
        recommended_products = []
        
        try:
            # Build the prompt with context and conversation history
            conversation_history = "\n\n".join(
                [f"{msg['role'].capitalize()}: {msg['content']}" 
                 for msg in st.session_state.conversation]
            )
            
            # Enhanced prompt for product recommendations
            full_prompt = f"""
            **ROLE**: You are a customer support expert for Puffy Mattresses.
            **CONTEXT**: {st.session_state.puffy_context}
            **CONVERSATION HISTORY**: {conversation_history}
            
            **INSTRUCTIONS**:
            1. Answer using ONLY information from CONTEXT
            2. Be concise, friendly and professional
            3. Remember previous questions and answers
            4. When recommending products, include the EXACT product name and URL from the context
            5. Format product recommendations as: [Product Name](URL)
            6. If answer isn't in context, say "I have limited information on this topic, but I recommend reaching out to their support team at support@puffy.com for more detailed assistance."
            
            **QUESTION**: {prompt}
            **ANSWER**:
            """
            
            # Generate response
            response = model.generate_content(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=500
                )
            )
            
            # Process response
            if response.text:
                # Extract recommended products from response
                response_text = response.text
                
                # Look for markdown links in the response
                markdown_links = re.findall(r'\[(.*?)\]\((https?://[^\s]+)\)', response_text)
                
                # Match found links with known products
                for link_text, url in markdown_links:
                    for product in st.session_state.all_products:
                        if product['url'] == url and product not in recommended_products:
                            recommended_products.append(product)
                
                # Simulate streaming for better UX
                chunks = response_text.split(" ")
                partial = ""
                for chunk in chunks:
                    partial += chunk + " "
                    time.sleep(0.05)
                    message_placeholder.markdown(partial + "▌")
                
                # Store final response
                full_response = partial.strip()
                message_placeholder.markdown(full_response)
                
                # Display product links separately if found
                if recommended_products:
                    st.markdown("**Recommended Products:**")
                    for product in recommended_products:
                        st.markdown(f"- [{product['name']}]({product['url']})")
            else:
                full_response = "I couldn't generate a response. Please try again."
                st.warning(full_response)
                
            # Show context stats
            st.caption(f"Used {len(full_prompt)//1000}K chars of context")
                
        except Exception as e:
            full_response = f"⚠️ Error: {str(e)}"
            st.error(full_response)
            st.info("Please try rephrasing your question or contact support@puffy.com")
        
        # Add assistant response to conversation
        assistant_message = {
            "role": "assistant", 
            "content": full_response
        }
        if recommended_products:
            assistant_message["recommended_products"] = recommended_products
        st.session_state.conversation.append(assistant_message)

# Add clear conversation button
if st.session_state.conversation:
    if st.button("Clear Conversation"):
        st.session_state.conversation = []
        st.rerun()