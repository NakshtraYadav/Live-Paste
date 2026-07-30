import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Link2, Zap, Users, Clock, ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LANGUAGES, EXPIRY_OPTIONS, API_BASE } from "@/lib/constants";

export default function HomePage() {
  const navigate = useNavigate();
  const [content, setContent] = useState("");
  const [customSlug, setCustomSlug] = useState("");
  const [language, setLanguage] = useState("plaintext");
  const [expiry, setExpiry] = useState("never");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    document.title = "LivePaste — Share text & code in real time";
  }, []);

  const handleCreate = async () => {
    if (creating) return;
    if (customSlug && !/^[a-zA-Z0-9_-]{3,64}$/.test(customSlug.trim())) {
      toast.error("Custom link must be 3-64 chars: letters, numbers, hyphens, underscores");
      return;
    }
    setCreating(true);
    try {
      const res = await axios.post(`${API_BASE}/api/paste`, {
        content,
        customSlug: customSlug.trim() || null,
        language,
        expiry,
      });
      const slug = res.data.slug;
      toast.success("Your live link is ready");
      navigate(`/${slug}`);
    } catch (err) {
      const msg = err?.response?.data?.detail || "Could not create the link. Please try again.";
      toast.error(msg);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Nav */}
      <header className="border-b border-border">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center">
              <Link2 className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="font-semibold tracking-tight text-lg" data-testid="app-logo">
              LivePaste
            </span>
          </div>
          <ThemeToggle testId="home-theme-toggle" />
        </div>
      </header>

      {/* Hero + create form */}
      <main className="flex-1">
        <section className="max-w-6xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
          <div className="max-w-3xl">
            <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight leading-[1.05]">
              Share text. Edit together.{" "}
              <span className="text-primary">Instantly.</span>
            </h1>
            <p className="mt-4 text-base md:text-lg text-muted-foreground max-w-xl">
              Paste anything — notes, code, configs. Get a link on this domain. Anyone with the
              link sees your edits live, no account needed.
            </p>
          </div>

          <Card className="mt-8 sm:mt-10 p-4 sm:p-6 bg-card border border-border rounded-xl shadow-sm">
            <textarea
              data-testid="create-paste-content-textarea"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={"Paste or type your text here…\nYou can keep editing after the link is created."}
              spellCheck={false}
              className="code-input w-full font-mono text-[13px] sm:text-sm leading-6 min-h-[220px] sm:min-h-[280px] bg-[hsl(var(--editor-bg))] text-[hsl(var(--editor-fg))] border border-border rounded-lg px-3 py-3 resize-y focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] placeholder:text-muted-foreground"
            />

            <div className="mt-4 grid grid-cols-1 sm:grid-cols-12 gap-3">
              <div className="sm:col-span-4">
                <label className="text-xs text-muted-foreground mb-1.5 block">
                  Custom link <span className="opacity-60">(optional)</span>
                </label>
                <div className="flex items-center">
                  <span className="font-mono text-xs text-muted-foreground bg-muted border border-r-0 border-border rounded-l-md px-2.5 h-9 inline-flex items-center">
                    /
                  </span>
                  <Input
                    data-testid="create-paste-custom-slug-input"
                    value={customSlug}
                    onChange={(e) => setCustomSlug(e.target.value)}
                    placeholder="my-notes"
                    className="rounded-l-none font-mono text-sm"
                  />
                </div>
              </div>
              <div className="sm:col-span-4">
                <label className="text-xs text-muted-foreground mb-1.5 block">Syntax</label>
                <Select value={language} onValueChange={setLanguage}>
                  <SelectTrigger data-testid="create-paste-language-select" className="w-full">
                    <SelectValue placeholder="Language" />
                  </SelectTrigger>
                  <SelectContent className="max-h-72">
                    {LANGUAGES.map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="sm:col-span-4">
                <label className="text-xs text-muted-foreground mb-1.5 block">Expiry</label>
                <Select value={expiry} onValueChange={setExpiry}>
                  <SelectTrigger data-testid="create-paste-expiry-select" className="w-full">
                    <SelectValue placeholder="Expiry" />
                  </SelectTrigger>
                  <SelectContent>
                    {EXPIRY_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="mt-5 flex items-center gap-3">
              <Button
                data-testid="create-paste-submit-button"
                onClick={handleCreate}
                disabled={creating}
                className="active:scale-[0.98]"
              >
                {creating ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Creating…
                  </>
                ) : (
                  <>
                    Create live link <ArrowRight className="h-4 w-4 ml-2" />
                  </>
                )}
              </Button>
              <p className="text-xs text-muted-foreground">
                Anyone with the link can view &amp; edit in real time.
              </p>
            </div>
          </Card>
        </section>

        {/* How it works */}
        <section className="max-w-6xl mx-auto px-4 sm:px-6 pb-14">
          <h2 className="text-base md:text-lg font-medium text-muted-foreground mb-5">
            How it works
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6">
            {[
              {
                icon: <Zap className="h-5 w-5 text-primary" />,
                title: "1. Create a link",
                body: "Paste your text or code, pick a custom link name if you like, and hit create.",
              },
              {
                icon: <Users className="h-5 w-5 text-primary" />,
                title: "2. Share it",
                body: "Send the link to anyone. No sign-up, no install — it just opens in the browser.",
              },
              {
                icon: <Clock className="h-5 w-5 text-primary" />,
                title: "3. Edit live together",
                body: "Everyone sees changes the moment they happen. Set an expiry to auto-delete.",
              },
            ].map((s) => (
              <Card key={s.title} className="p-5 bg-card border border-border rounded-xl">
                <div className="h-9 w-9 rounded-lg bg-secondary flex items-center justify-center">
                  {s.icon}
                </div>
                <h3 className="mt-3 font-medium">{s.title}</h3>
                <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed">{s.body}</p>
              </Card>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            LivePaste — anonymous real-time text sharing. Pastes with an expiry are deleted
            automatically.
          </p>
          <p className="text-xs text-muted-foreground font-mono">no accounts · no tracking</p>
        </div>
      </footer>
    </div>
  );
}
