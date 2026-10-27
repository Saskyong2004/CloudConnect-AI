// AWS API Gateway endpoint (API_BASE comes from config.js)
const API_URL = `${API_BASE}/contact`;


// Get form elements
const form = document.getElementById("contactForm");
const button = document.getElementById("submitButton");
const status = document.getElementById("formStatus");


// Handle form submission
form.addEventListener("submit", async (event) => {

    event.preventDefault();

    // Get form values
    const name = document.getElementById("name").value.trim();
    const email = document.getElementById("email").value.trim();
    const message = document.getElementById("message").value.trim();

    // Basic validation
    if (!name || !email || !message) {
        status.textContent = "Please fill in all fields.";
        status.style.color = "#dc2626";
        return;
    }

    // Disable button while submitting
    button.disabled = true;
    button.textContent = "Sending...";

    status.textContent = "";

    try {

        // Send data to AWS API Gateway
        const response = await fetch(API_URL, {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                name: name,
                email: email,
                message: message
            })
        });


        // Read API response
        const result = await response.json();


        if (response.ok && result.success) {

            const tag = result.sentiment && result.sentiment !== "UNANALYZED"
                ? ` (AI detected: ${result.sentiment.toLowerCase()} · ${result.category})`
                : "";
            status.textContent =
                "✓ Message submitted successfully!" + tag;

            status.style.color = "#16a34a";

            // Clear form
            form.reset();

        } else {

            throw new Error(
                result.message || "Something went wrong."
            );
        }

    } catch (error) {

        console.error("Submission error:", error);

        status.textContent =
            "Unable to submit message. Please try again.";

        status.style.color = "#dc2626";

    } finally {

        // Enable button again
        button.disabled = false;
        button.textContent = "Submit Message →";
    }

});