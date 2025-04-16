import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { loadStripe, Stripe } from '@stripe/stripe-js';
import {
    Elements,
    CardElement,
    useStripe,
    useElements
} from '@stripe/react-stripe-js';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Label } from '../components/ui/label';
import { AlertCircle } from 'lucide-react';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const STRIPE_PUBLISHABLE_KEY = process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY;

// Ensure Stripe key is loaded before rendering the Elements provider
let stripePromise: Promise<Stripe | null> | null = null;
if (STRIPE_PUBLISHABLE_KEY) {
    stripePromise = loadStripe(STRIPE_PUBLISHABLE_KEY);
} else {
    console.error("Stripe Publishable Key is not set in environment variables.");
}

interface TokenPackage {
    id: string;
    name: string;
    amountTokens: number;
    priceUSD: number;
}

// TODO: Fetch packages from backend or define statically
const tokenPackages: TokenPackage[] = [
    { id: '100_tokens', name: '100 Tokens', amountTokens: 100, priceUSD: 1.00 },
    { id: '500_tokens', name: '550 Tokens', amountTokens: 550, priceUSD: 5.00 }, // Bonus!
    { id: '1000_tokens', name: '1200 Tokens', amountTokens: 1200, priceUSD: 10.00 }, // Bigger Bonus!
];

const CheckoutForm: React.FC<{ selectedPackage: TokenPackage }> = ({ selectedPackage }) => {
    const stripe = useStripe();
    const elements = useElements();
    const { token } = useAuth();
    const navigate = useNavigate();
    const [error, setError] = useState<string | null>(null);
    const [processing, setProcessing] = useState<boolean>(false);

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        setProcessing(true);
        setError(null);

        if (!stripe || !elements) {
            setError('Stripe has not loaded yet.');
            setProcessing(false);
            return;
        }

        const cardElement = elements.getElement(CardElement);
        if (!cardElement) {
            setError('Card details not found.');
            setProcessing(false);
            return;
        }

        try {
            // 1. Create Payment Intent on backend
            const intentResponse = await axios.post(
                `${API_URL}/api/tokens/purchase/intent`,
                {
                    amount_usd: selectedPackage.priceUSD,
                    token_package: selectedPackage.id
                },
                {
                    headers: {
                        Authorization: `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    }
                }
            );

            const clientSecret = intentResponse.data.client_secret;

            if (!clientSecret) {
                throw new Error('Failed to get payment intent from server.');
            }

            // 2. Confirm the card payment
            const paymentResult = await stripe.confirmCardPayment(clientSecret, {
                payment_method: {
                    card: cardElement,
                    // billing_details: { name: 'Jenny Rosen' }, // Optional
                },
            });

            if (paymentResult.error) {
                setError(paymentResult.error.message || 'Payment failed');
            } else {
                if (paymentResult.paymentIntent.status === 'succeeded') {
                    // Payment succeeded! Navigate or show success message
                    // The webhook will handle granting tokens, but we can give immediate feedback
                    alert('Payment successful! Tokens will be added shortly.');
                    navigate('/dashboard'); // Or to a confirmation page
                } else {
                     setError(`Payment status: ${paymentResult.paymentIntent.status}`);
                }
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || err.message || 'An unexpected error occurred');
        } finally {
            setProcessing(false);
        }
    };

    return (
        <form onSubmit={handleSubmit}>
            {error && (
                <div className="bg-destructive/10 text-destructive border-l-4 border-destructive p-4 mb-4 flex items-start" role="alert">
                    <AlertCircle className="h-5 w-5 mr-2 flex-shrink-0" />
                    <p>{error}</p>
                </div>
            )}
            <div className="mb-4">
                 <Label htmlFor="card-element">Card Details</Label>
                <CardElement id="card-element" className="p-3 border rounded-md mt-1" />
            </div>
            <Button
                type="submit"
                disabled={!stripe || processing}
                className="w-full"
            >
                {processing ? 'Processing...' : `Pay $${selectedPackage.priceUSD.toFixed(2)}`}
            </Button>
        </form>
    );
};

const PurchaseTokens: React.FC = () => {
    const navigate = useNavigate();
    const [selectedPackage, setSelectedPackage] = useState<TokenPackage | null>(tokenPackages[0]); // Default selection

    if (!stripePromise) {
        return <div className="p-6">Error: Stripe could not be loaded. Check console.</div>;
    }

    return (
        <div className="min-h-screen bg-gray-100 flex items-center justify-center">
            <Card className="w-full max-w-lg">
                <CardHeader>
                    <CardTitle>Purchase Tokens</CardTitle>
                    <CardDescription>Select a package and complete your purchase.</CardDescription>
                    <button
                        onClick={() => navigate(-1)} // Go back
                        className="absolute top-4 right-4 text-gray-500 hover:text-gray-700"
                    >
                        &times; {/* Close button */}
                    </button>
                </CardHeader>
                <CardContent>
                    <div className="mb-6">
                        <Label>Select Package</Label>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-2">
                            {tokenPackages.map((pkg) => (
                                <Button
                                    key={pkg.id}
                                    variant={selectedPackage?.id === pkg.id ? 'default' : 'outline'}
                                    onClick={() => setSelectedPackage(pkg)}
                                    className="flex flex-col h-auto p-4 text-left"
                                >
                                    <span className="font-semibold">{pkg.name}</span>
                                    <span className="text-sm text-muted-foreground">${pkg.priceUSD.toFixed(2)}</span>
                                </Button>
                            ))}
                        </div>
                    </div>

                    {selectedPackage && (
                        <Elements stripe={stripePromise}>
                            <CheckoutForm selectedPackage={selectedPackage} />
                        </Elements>
                    )}
                </CardContent>
            </Card>
        </div>
    );
};

export default PurchaseTokens; 