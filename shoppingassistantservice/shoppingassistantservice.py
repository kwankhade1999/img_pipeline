#!/usr/bin/python

import os

from urllib.parse import unquote
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_postgres import PGVector
from flask import Flask, request

DATABASE_URL = os.environ["DATABASE_URL"]
COLLECTION_NAME = os.environ["COLLECTION_NAME"]

vectorstore = PGVector(
    embeddings=OpenAIEmbeddings(model="text-embedding-3-small"),
    collection_name=COLLECTION_NAME,
    connection=DATABASE_URL,
)

def create_app():
    app = Flask(__name__)

    @app.route("/", methods=['POST'])
    def talkToOpenAI():
        print("Beginning RAG call")
        prompt = request.json['message']
        prompt = unquote(prompt)
        image_url = request.json['image']

        # Step 1 – Get a room description from GPT-4o vision
        llm_vision = ChatOpenAI(model="gpt-4o")
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": "You are a professional interior designer, give me a detailed description of the style of the room in this image",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ]
        )
        response = llm_vision.invoke([message])
        print("Description step:")
        print(response)
        description_response = response.content

        # Step 2 – Similarity search with the description & user prompt
        vector_search_prompt = f""" This is the user's request: {prompt} Find the most relevant items for that prompt, while matching style of the room described here: {description_response} """
        print(vector_search_prompt)

        docs = vectorstore.similarity_search(vector_search_prompt)
        print(f"Vector search description: {description_response}")
        print(f"Retrieved documents: {len(docs)}")
        # Prepare relevant documents for inclusion in final prompt
        relevant_docs = ""
        for doc in docs:
            doc_details = doc.to_json()
            print(f"Adding relevant document to prompt context: {doc_details}")
            relevant_docs += str(doc_details) + ", "

        # Step 3 – Tie it all together by augmenting our call to GPT-4o
        llm = ChatOpenAI(model="gpt-4o")
        design_prompt = (
            f" You are an interior designer that works for Online Boutique. You are tasked with providing recommendations to a customer on what they should add to a given room from our catalog. This is the description of the room: \n"
            f"{description_response} Here are a list of products that are relevant to it: {relevant_docs} Specifically, this is what the customer has asked for, see if you can accommodate it: {prompt} Start by repeating a brief description of the room's design to the customer, then provide your recommendations. Do your best to pick the most relevant item out of the list of products provided, but if none of them seem relevant, then say that instead of inventing a new product. At the end of the response, add a list of the IDs of the relevant products in the following format for the top 3 results: [<first product ID>], [<second product ID>], [<third product ID>] ")
        print("Final design prompt: ")
        print(design_prompt)
        design_response = llm.invoke(design_prompt)

        data = {'content': design_response.content}
        return data

    return app

if __name__ == "__main__":
    # Create an instance of flask server when called directly
    app = create_app()
    app.run(host='0.0.0.0', port=8080)
