# Questioner 

step 1: create and venv and activate it 

step 2 :download all the packages in requirements.txt (there are 2 files with the same name download the one outside the files folder ) 

step 2 : now cd into the files "cd files" (side note use "cd .." to change the directory to outside foler )  

step 3 :create an .env files and then fill the following api keys 
        AZURE_SPEECH_KEY=
        GROQ_API_KEY=
        DEFAULT_VOICE=
       # DATABASE CONFIGURATION
        DB_HOST=
        DB_PORT=
        DB_NAME=
        DB_USER=
        DB_PASSWORD=
        DATABASE_URL=


step 3 : run the fast api using the following code "uvicorn main:app --port 8001 --reload" 

step 4 : run the html file 
